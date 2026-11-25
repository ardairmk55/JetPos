"""Yazıcı köprüsü uçları. Oturum/çerez kullanılmaz; her istek şubeye özel anahtarla (Bearer) doğrulanır."""
import base64
import hashlib
import secrets

from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import PrintAgent, PrintJob


def hash_token(token):
    # Anahtar 256 bit rastgele olduğu için hızlı özet yeterlidir.
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(business, branch):
    """Yeni anahtar üretir; önceki anahtar anında geçersiz olur. Düz metin yalnızca burada döner."""
    token = secrets.token_urlsafe(32)
    PrintAgent.objects.update_or_create(branch=branch, defaults={
        "business": business, "token_hash": hash_token(token), "last_seen_at": None})
    return token


class _AgentView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def agent(self, request):
        scheme, _, token = request.headers.get("Authorization", "").partition(" ")
        if scheme != "Bearer" or not token.strip():
            return None
        agent = PrintAgent.objects.select_related("branch", "business").filter(
            token_hash=hash_token(token.strip()), branch__is_active=True).first()
        if agent:
            PrintAgent.objects.filter(pk=agent.pk).update(last_seen_at=timezone.now())
        return agent

    def denied(self):
        return Response({"detail": "Yazıcı köprüsü anahtarı geçersiz", "code": "bad_agent_token"}, status=401)


class ClaimView(_AgentView):
    def post(self, request):
        agent = self.agent(request)
        if not agent:
            return self.denied()
        claimed = services.claim_for_agent(agent.branch)
        if not claimed:
            return Response({"job": None})
        job, target, data = claimed
        return Response({"job": {
            "id": job.id, "title": job.title, "printer": target.name, "connection": target.connection,
            "address": target.address, "port": target.port, "data": base64.b64encode(data).decode()}})


class ResultView(_AgentView):
    def post(self, request):
        agent = self.agent(request)
        if not agent:
            return self.denied()
        job_id = str(request.data.get("job", ""))
        job = None
        if job_id.isdecimal() and len(job_id) < 18:
            job = PrintJob.objects.filter(pk=int(job_id), branch=agent.branch, printer__via_agent=True).first()
        if not job:
            return Response({"detail": "İş bulunamadı"}, status=404)
        job = services.report_from_agent(job, request.data.get("ok") is True, str(request.data.get("error") or ""))
        return Response({"status": job.status})
