"""``{% family_context_field %}``: the family a form was rendered for (S-16).

Every ``method="post"`` form posting to an ``entries`` or ``family_access``
view includes it next to ``{% csrf_token %}``; ``FamilyContextMiddleware``
refuses a submission whose family is no longer the current one.
"""

from django import template
from django.utils.html import format_html

from family_access.context import FORM_FIELD, peek_family_context

register = template.Library()


@register.simple_tag(takes_context=True)
def family_context_field(context):
    request = context.get('request')
    if request is None:
        return ''
    membership, _count = peek_family_context(request)
    if membership is None:
        return ''
    return format_html('<input type="hidden" name="{}" value="{}">', FORM_FIELD, membership.family_id)
