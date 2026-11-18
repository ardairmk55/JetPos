from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .notify import branch_group, role_group, user_group


class BranchConsumer(AsyncJsonWebsocketConsumer):
    """Şube canlı kanalı: masa, mutfak, hazır sipariş ve bildirim olayları (LAN üzerinden)."""

    async def connect(self):
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.close(code=4401)
            return
        branch_id = await self._branch_id(user)
        self.groups_joined = [user_group(user.id)]
        if branch_id:
            self.groups_joined += [branch_group(branch_id), role_group(branch_id, user.role)]
        for g in self.groups_joined:
            await self.channel_layer.group_add(g, self.channel_name)
        await self.accept()
        await self.send_json({"event": "hello", "data": {"branch": branch_id, "user": user.id}})

    @database_sync_to_async
    def _branch_id(self, user):
        from .models import Branch
        from .roles import BRANCH_SCOPED_ROLES

        qs = self.scope.get("query_string", b"").decode()
        requested = None
        for part in qs.split("&"):
            if part.startswith("branch="):
                requested = part.split("=", 1)[1]
        if user.role in BRANCH_SCOPED_ROLES or not requested or not requested.isdigit():
            if user.branch_id:
                return user.branch_id
            b = Branch.objects.filter(business_id=user.business_id).order_by("id").first()
            return b.id if b else None
        b = Branch.objects.filter(business_id=user.business_id, pk=int(requested)).first()
        return b.id if b else user.branch_id

    async def disconnect(self, code):
        for g in getattr(self, "groups_joined", []):
            await self.channel_layer.group_discard(g, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if content.get("type") == "ping":
            await self.send_json({"event": "pong"})

    async def push(self, message):
        await self.send_json({"event": message["event"], "data": message["data"]})
