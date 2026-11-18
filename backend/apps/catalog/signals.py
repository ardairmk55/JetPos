from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import PriceHistory, Product, ProductPrice


@receiver(pre_save, sender=Product)
def _remember_price(sender, instance, **kwargs):
    instance._old_price = None
    if instance.pk:
        instance._old_price = Product.objects.filter(pk=instance.pk).values_list("base_price", flat=True).first()


@receiver(post_save, sender=Product)
def _log_price(sender, instance, created, **kwargs):
    old = getattr(instance, "_old_price", None)
    if created or (old is not None and old != instance.base_price):
        PriceHistory.objects.create(business=instance.business, product=instance, scope="base",
                                    old_price=None if created else old, new_price=instance.base_price,
                                    user=getattr(instance, "_actor", None))
    from apps.integrations.services import queue_catalog_change

    queue_catalog_change(instance)


@receiver(post_save, sender=ProductPrice)
def _log_scoped_price(sender, instance, created, **kwargs):
    scope = f"channel={instance.channel or '*'} branch={instance.branch_id or '*'} group={instance.customer_group_id or '*'}"
    PriceHistory.objects.create(business=instance.business, product=instance.product, scope=scope,
                                old_price=None, new_price=instance.price, user=getattr(instance, "_actor", None))
