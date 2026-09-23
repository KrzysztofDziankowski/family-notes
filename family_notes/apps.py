from django.contrib.admin.apps import AdminConfig


class FamilyNotesAdminConfig(AdminConfig):
    default_site = 'family_notes.admin.SuperuserAdminSite'
