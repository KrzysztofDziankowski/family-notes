from django.apps import AppConfig


class FamilyAccessConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'family_access'

    def ready(self):
        from . import notices  # noqa: F401  (connects the sign-in receiver)
