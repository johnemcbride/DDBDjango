"""
dynamo_backend.admin
~~~~~~~~~~~~~~~~~~~~~
DynamoModelAdmin — a Django ModelAdmin subclass that works with DynamoModel
instead of Django ORM models.

Usage in your app's admin.py::

    from dynamo_backend.admin import DynamoModelAdmin
    from django.contrib import admin
    from .models import Author, Post

    @admin.register(Author)
    class AuthorAdmin(DynamoModelAdmin):
        list_display = ("pk", "username", "email", "created_at")
        search_fields = ("username",)

    @admin.register(Post)
    class PostAdmin(DynamoModelAdmin):
        list_display = ("pk", "title", "slug", "published", "created_at")
"""

from __future__ import annotations

import json as _json
from typing import Any, Dict, List, Optional

from django import forms
from django.contrib import admin
from django.contrib.admin.options import ModelAdmin


# ─────────────────────────────────────────────── queryset adapter

class _FakeQuery:
    """Minimal stub for Django ORM's QuerySet.query interface used by admin internals."""
    select_related = False
    order_by = ()
    standard_ordering = True

    # django.contrib.admin.views.main accesses these in various places
    def is_empty(self):
        return False

    def __bool__(self):
        return False


class DynamoAdminQuerySet:
    """
    Wraps DynamoQuerySet to present the minimal DataFrame-like interface that
    django.contrib.admin's ChangeList and action handling expect.
    """

    # Django admin's ChangeList reads qs.query.select_related
    query = _FakeQuery()

    def __init__(self, model_cls, items=None):
        self._model_cls = model_cls
        self._items: Optional[List] = items  # None = not yet fetched
        self.query = _FakeQuery()  # per-instance so clones are independent

    # ────────────────────────────────────── lazy fetch

    def _resolve(self) -> List:
        if self._items is None:
            self._items = list(self._model_cls.objects.all())
        return self._items

    def _clone(self, items=None) -> "DynamoAdminQuerySet":
        return DynamoAdminQuerySet(self._model_cls, items)

    # ────────────────────────────────────── Django queryset interface

    @property
    def model(self):
        return self._model_cls

    @property
    def verbose_name(self):
        return self._model_cls._meta.verbose_name

    @property
    def verbose_name_plural(self):
        return self._model_cls._meta.verbose_name_plural

    # db is sometimes read by Django admin pagination
    db = "default"

    def all(self):
        return self._clone()

    def filter(self, *args, **kwargs):
        # pk__in: used by bulk admin actions on selected rows
        if "pk__in" in kwargs:
            pks = set(str(p) for p in kwargs["pk__in"])
            items = []
            for pk in pks:
                try:
                    items.append(self._model_cls.objects.get(pk=pk))
                except Exception:
                    pass
            return self._clone(items)

        # single pk lookup
        if "pk" in kwargs:
            try:
                return self._clone([self._model_cls.objects.get(pk=kwargs["pk"])])
            except Exception:
                return self._clone([])

        # For complex ORM predicates we can't translate — return all (admin
        # only uses these for search, which DynamoDB would need a full scan for).
        return self._clone()

    def exclude(self, *args, **kwargs):
        return self._clone()

    def order_by(self, *fields):
        items = list(self._resolve())
        for field in reversed(fields):
            reverse = field.startswith("-")
            key = field.lstrip("-")
            try:
                items.sort(
                    key=lambda x, k=key: (getattr(x, k, None) or ""),
                    reverse=reverse,
                )
            except Exception:
                pass
        return self._clone(items)

    def select_related(self, *args):
        return self

    def prefetch_related(self, *args):
        return self

    def annotate(self, *args, **kwargs):
        return self

    def distinct(self):
        return self

    def using(self, db):
        return self

    def none(self):
        return self._clone([])

    def complex_filter(self, filter_obj):
        """Used by Django admin's search (Q objects). We can't translate — return all."""
        return self

    def count(self) -> int:
        return len(self._resolve())

    def values_list(self, *fields, flat=False):
        items = self._resolve()
        if flat and len(fields) == 1:
            fname = fields[0]
            return [str(getattr(item, fname, "")) for item in items]
        return [tuple(str(getattr(item, f, "")) for f in fields) for item in items]

    def delete(self):
        items = self._resolve()
        for item in items:
            item.delete()
        return (len(items), {repr(self._model_cls): len(items)})

    def __iter__(self):
        return iter(self._resolve())

    def __len__(self) -> int:
        return len(self._resolve())

    def __getitem__(self, k):
        return self._resolve()[k]

    def __bool__(self):
        return bool(self._resolve())


# ─────────────────────────────────────────────── form helpers

def _dynamo_to_form_field(dynamo_field) -> Optional[forms.Field]:
    """Map a Dynamo Field instance to a Django Form field. Returns None for
    auto-managed fields that should be hidden from the admin form."""
    from dynamo_backend.fields import (
        BooleanField, IntegerField, FloatField,
        DateTimeField, JSONField, ListField, CharField,
    )

    if isinstance(dynamo_field, BooleanField):
        return forms.BooleanField(required=False)

    if isinstance(dynamo_field, IntegerField):
        return forms.IntegerField(required=False)

    if isinstance(dynamo_field, FloatField):
        return forms.FloatField(required=False)

    if isinstance(dynamo_field, DateTimeField):
        if dynamo_field.auto_now or dynamo_field.auto_now_add:
            return None  # auto-managed — don't expose in the form
        return forms.DateTimeField(
            required=False,
            widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
        )

    if isinstance(dynamo_field, (JSONField, ListField)):
        return forms.CharField(
            required=False,
            widget=forms.Textarea(attrs={"rows": 3, "style": "font-family:monospace"}),
            help_text="Enter valid JSON",
        )

    # CharField, UUIDField, etc.
    max_length = getattr(dynamo_field, "max_length", None)
    if max_length and max_length > 300:
        return forms.CharField(
            required=False,
            widget=forms.Textarea(attrs={"rows": 5}),
            max_length=max_length,
        )
    return forms.CharField(required=False, max_length=max_length)


def _make_admin_form(model_cls):
    """
    Dynamically build a Django ``forms.Form`` subclass for the given
    DynamoModel, excluding the pk and any auto-managed datetime fields.
    """
    from dynamo_backend.fields import JSONField, ListField

    field_defs: Dict[str, forms.Field] = {}
    for name, dynamo_field in model_cls._meta.fields.items():
        if dynamo_field.primary_key:
            continue
        form_field = _dynamo_to_form_field(dynamo_field)
        if form_field is None:
            continue
        form_field.label = name.replace("_", " ").title()
        field_defs[name] = form_field

    def _init(self, *args, instance=None, **kwargs):
        # Store instance so save_form can find it later
        self._dynamo_instance = instance
        # Django admin templates access form.instance.pk for change URLs
        self.instance = instance

        # On GET (no POST data), seed initial values from the instance
        if instance is not None and not args and "data" not in kwargs:
            initial: Dict[str, Any] = {}
            for fname in field_defs:
                val = getattr(instance, fname, None)
                f_obj = model_cls._meta.fields.get(fname)
                if isinstance(f_obj, (JSONField, ListField)) and val is not None:
                    try:
                        initial[fname] = _json.dumps(val, default=str)
                    except Exception:
                        initial[fname] = str(val)
                else:
                    initial[fname] = val
            kwargs.setdefault("initial", initial)

        super(DynamoAdminForm, self).__init__(*args, **kwargs)

    DynamoAdminForm = type(
        f"{model_cls.__name__}AdminForm",
        (forms.Form,),
        {"__init__": _init, **field_defs},
    )
    return DynamoAdminForm


# ─────────────────────────────────────────────── ModelAdmin subclass

class DynamoModelAdmin(ModelAdmin):
    """
    Drop-in replacement for ``django.contrib.admin.ModelAdmin`` that works
    with DynamoModel subclasses instead of Django ORM models.
    """

    # ── queryset / object retrieval

    def get_queryset(self, request):
        return DynamoAdminQuerySet(self.model)

    def get_object(self, request, object_id, from_field=None):
        try:
            return self.model.objects.get(pk=object_id)
        except self.model.DoesNotExist:
            return None
        except Exception:
            return None

    # ── form handling

    def get_form(self, request, obj=None, change=False, **kwargs):
        return _make_admin_form(self.model)

    def save_form(self, request, form, change):
        """
        Apply form.cleaned_data to the model instance and return it
        (without saving — save_model does that).
        """
        from dynamo_backend.fields import JSONField, ListField

        # Retrieve the original instance (stored by the form's __init__)
        obj = getattr(form, "_dynamo_instance", None)
        if obj is None:
            obj = self.model()

        for fname, val in form.cleaned_data.items():
            f_obj = self.model._meta.fields.get(fname)
            # Convert JSON-string back to Python object for JSON/List fields
            if isinstance(f_obj, (JSONField, ListField)) and isinstance(val, str):
                if val.strip():
                    try:
                        val = _json.loads(val)
                    except Exception:
                        pass  # keep as string — validation will catch it later
                else:
                    val = f_obj.get_default()
            # Convert empty string to None for nullable fields with no default
            if val == "" and f_obj is not None and f_obj.nullable:
                val = None
            setattr(obj, fname, val)

        return obj

    def save_model(self, request, obj, form, change):
        obj.save()

    def delete_model(self, request, obj):
        obj.delete()

    def save_related(self, request, form, formsets, change):
        """No-op: DynamoDB models have no M2M relations or inline formsets."""
        pass

    # ── list display helpers

    def get_list_display(self, request):
        if self.list_display and self.list_display != ("__str__",):
            return self.list_display
        # Auto: pk + first 4 non-auto fields
        fields = ["pk"]
        for name, f in self.model._meta.fields.items():
            from dynamo_backend.fields import DateTimeField
            if not f.primary_key and not (
                isinstance(f, DateTimeField) and (f.auto_now or f.auto_now_add)
            ):
                fields.append(name)
                if len(fields) >= 5:
                    break
        return fields

    # ── permissions (always allow when DEBUG)

    def has_add_permission(self, request):
        return True

    def has_change_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return True

    def has_view_permission(self, request, obj=None):
        return True

    # ── search: do a simple Python-side substring filter

    def get_search_results(self, request, queryset, search_term):
        if not search_term or not self.search_fields:
            return queryset, False
        matched = [
            obj for obj in queryset
            if any(
                search_term.lower() in str(getattr(obj, f, "") or "").lower()
                for f in self.search_fields
            )
        ]
        return DynamoAdminQuerySet(self.model, matched), False

    # ── delete flow: bypass Django's ORM-based NestedObjects collector

    def get_deleted_objects(self, objs, request):
        """
        Override to skip Django's SQL Collector entirely.
        Returns the minimal (to_delete, model_count, perms_needed, protected)
        tuple that the deletion confirmation template expects.
        """
        from django.utils.text import capfirst
        from django.utils.html import format_html
        from django.urls import reverse, NoReverseMatch
        from urllib.parse import quote

        opts = self.model._meta
        to_delete = []
        perms_needed = set()

        for obj in objs:
            label = "%s: %s" % (capfirst(opts.verbose_name), obj)
            if not self.has_delete_permission(request, obj):
                perms_needed.add(opts.verbose_name)
                to_delete.append(label)
            else:
                try:
                    admin_url = reverse(
                        "%s:%s_%s_change" % (
                            self.admin_site.name, opts.app_label, opts.model_name
                        ),
                        None,
                        (quote(str(obj.pk)),),
                    )
                    to_delete.append(format_html(
                        '{}: <a href="{}">{}</a>',
                        capfirst(opts.verbose_name), admin_url, obj,
                    ))
                except NoReverseMatch:
                    to_delete.append(label)

        model_count = {opts.verbose_name_plural: len(list(objs))}
        return to_delete, model_count, perms_needed, []

    def delete_queryset(self, request, queryset):
        """Bulk-delete: iterate and call .delete() on each instance."""
        for obj in queryset:
            obj.delete()

    # ── change-log: no-op (DynamoDB models have no ContentType / LogEntry)

    def log_addition(self, request, obj, message):
        pass

    def log_change(self, request, obj, message):
        pass

    def log_deletion(self, request, obj, object_repr):
        pass

    def log_deletions(self, request, queryset):
        """Django 6.0 bulk-delete log hook — no-op for DynamoDB models."""
        pass

    # ── response helpers: redirect to changelist after add/change/delete

    def response_add(self, request, obj, post_url_continue=None):
        from django.contrib import messages
        from django.http import HttpResponseRedirect
        from django.urls import reverse
        opts = self.model._meta
        messages.success(
            request,
            f"The {opts.verbose_name} \"{obj}\" was added successfully.",
        )
        if "_addanother" in request.POST:
            return HttpResponseRedirect(
                reverse(
                    f"{self.admin_site.name}:{opts.app_label}_{opts.model_name}_add"
                )
            )
        if "_continue" in request.POST:
            from urllib.parse import quote
            return HttpResponseRedirect(
                reverse(
                    f"{self.admin_site.name}:{opts.app_label}_{opts.model_name}_change",
                    args=(quote(str(obj.pk)),),
                )
            )
        return HttpResponseRedirect(
            reverse(
                f"{self.admin_site.name}:{opts.app_label}_{opts.model_name}_changelist"
            )
        )

    def response_change(self, request, obj):
        from django.contrib import messages
        from django.http import HttpResponseRedirect
        from django.urls import reverse
        from urllib.parse import quote
        opts = self.model._meta
        messages.success(
            request,
            f"The {opts.verbose_name} \"{obj}\" was changed successfully.",
        )
        if "_continue" in request.POST:
            return HttpResponseRedirect(
                reverse(
                    f"{self.admin_site.name}:{opts.app_label}_{opts.model_name}_change",
                    args=(quote(str(obj.pk)),),
                )
            )
        return HttpResponseRedirect(
            reverse(
                f"{self.admin_site.name}:{opts.app_label}_{opts.model_name}_changelist"
            )
        )


# ─────────────────────────────────────────────── DynamoUser admin
# DynamoUser extends AbstractUser so Django's built-in UserAdmin works
# out-of-the-box. Groups/permissions use DynamoManyToManyField.

from django.contrib.auth.admin import UserAdmin as _DjangoUserAdmin
from dynamo_backend.user_model import DynamoUser

admin.site.register(DynamoUser, _DjangoUserAdmin)
