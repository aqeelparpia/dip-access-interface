"""
Model classes declaration for dips app:

To connect Django models to elasticsearch-dsl documents declared in
search.documents, an AbstractEsModel has been created with the ABC and
Django model metas. The models extending AbstractEsModel must implement
an `es_doc` attribute with the related DocType class from search.documents
and a `get_es_data` method to transform to a dictionary representation of
the ES document.
"""
from abc import ABCMeta, abstractmethod
from collections import OrderedDict
from django.contrib.auth.models import Group, AbstractUser
from django.db import models
from django.utils.translation import gettext, gettext_lazy as _
from django_celery_results.models import TaskResult as CeleryTaskResult
from jsonfield import JSONField

from search.documents import CollectionDoc, DIPDoc, DigitalFileDoc
from search.helpers import delete_document
from scope.celery import app as celery_app
from .helpers import add_if_not_empty


class TaskResult(CeleryTaskResult):
    """Proxy model to generate error message from Celery TaskResult"""
    class Meta:
        proxy = True

    def get_error_message(self):
        """Format traceback as HTML to display in alert"""
        message = gettext('Error trace:') + '<p><pre>%s</pre></p>' % self.traceback
        return message


class User(AbstractUser):
    def group_names(self):
        return ', '.join(list(self.groups.values_list('name', flat=True)))

    def is_editor(self):
        return (
            self.is_superuser or
            self.groups.filter(name='Editors').exists()
        )

    def is_manager(self):
        return (
            self.is_superuser or
            self.groups.filter(name='Managers').exists()
        )

    @classmethod
    def get_users(cls, query=None, sort_field='username'):
        """
        Get users based on a query string, querying over 'username',
        'first_name', 'last_name', 'email' and a concatenation of related
        group names separated by ', '. The group name concatenation
        can be used to sort and display in the 'group_names' field and the
        output will be the same as the equally called function from this model.
        The resulting users will be ordered by a given 'sort_field'. Returns
        all users if no query is given and sorts by 'username' by default.
        """
        class GroupsSQ(models.Subquery):
            """Subquery to concatenate group names, requires MySQL or SQLite"""
            template = "(SELECT GROUP_CONCAT(name, ', ') FROM (%(subquery)s))"
            output_field = models.CharField()

        subquery = GroupsSQ(Group.objects.filter(user=models.OuterRef('pk')))
        users = cls.objects.annotate(group_names=subquery).order_by(sort_field)
        if not query:
            return users.all()
        return users.filter(
            models.Q(username__icontains=query) |
            models.Q(first_name__icontains=query) |
            models.Q(last_name__icontains=query) |
            models.Q(email__icontains=query) |
            models.Q(group_names__icontains=query)
        )


class AbstractModelMeta(ABCMeta, type(models.Model)):
    """Meta merged from ABC and Django models to use in AbstractEsModel."""


class AbstractEsModel(models.Model, metaclass=AbstractModelMeta):
    """Abstract base model for models related to ES DocTypes."""
    class Meta:
        abstract = True

    def save(self, update_es=True, *args, **kwargs):
        """Extended save to optionally update related documents in ES."""
        super(AbstractEsModel, self).save(*args, **kwargs)
        if not update_es:
            return
        # Use refresh to reflect the changes in the index in the same request
        self.to_es_doc().save(refresh=True)
        # Update descendant DigitalFiles if needed
        if self.requires_es_descendants_update():
            # Launch async. task by name to avoid circular imports
            # or to import the task within this function.
            celery_app.send_task(
                'dips.tasks.update_es_descendants',
                args=(self.__class__.__name__, self.pk))

    def delete(self, *args, **kwargs):
        """Extended delete to remove related documents in ES."""
        self.delete_es_doc()
        # Delete descendants if needed
        if self.requires_es_descendants_delete():
            # Launch async. task by name to avoid circular imports
            # or to import the task within this function.
            celery_app.send_task(
                'dips.tasks.delete_es_descendants',
                args=(self.__class__.__name__, self.pk))
        super(AbstractEsModel, self).delete(*args, **kwargs)

    # Declaration in abstract class must be as property to allow decorators.
    # Implementation in descendats must be as attribute to avoid setter/getter.
    @property
    @abstractmethod
    def es_doc(self):
        """Related ES DocType from search.documents."""

    @abstractmethod
    def get_es_data(self):
        """Model transformation to ES metadata dict."""

    @abstractmethod
    def requires_es_descendants_update(self):
        """Checks if descendants need to be updated in ES."""

    @abstractmethod
    def requires_es_descendants_delete(self):
        """Checks if descendants need to be updated in ES."""

    def to_es_doc(self):
        """Model transformation to related DocType."""
        data = self.get_es_data()
        return self.es_doc(meta={'id': data.pop('_id')}, **data)

    def delete_es_doc(self):
        """Call to remove related document from the ES index."""
        delete_document(
            index=self.es_doc._index._name,
            doc_type=self.es_doc._doc_type.name,
            id=self.pk,
        )


class DublinCore(models.Model):
    identifier = models.CharField(_('identifier'), max_length=50)
    title = models.CharField(_('title'), max_length=200, blank=True)
    creator = models.CharField(_('creator'), max_length=200, blank=True)
    subject = models.CharField(_('subject'), max_length=200, blank=True)
    description = models.TextField(_('description'), blank=True)
    publisher = models.CharField(_('publisher'), max_length=200, blank=True)
    contributor = models.CharField(_('contributor'), max_length=200, blank=True)
    date = models.CharField(_('date'), max_length=21, blank=True)
    type = models.CharField(_('type'), max_length=200, blank=True)
    format = models.TextField(_('format'), blank=True)
    source = models.CharField(_('source'), max_length=200, blank=True)
    language = models.CharField(_('language'), max_length=200, blank=True)
    coverage = models.CharField(_('coverage'), max_length=200, blank=True)
    rights = models.CharField(_('rights'), max_length=200, blank=True)

    REQUIRED_FIELDS = ['identifier']
    ORDERED_FIELDS = [
        'identifier', 'title', 'creator', 'subject', 'description', 'publisher',
        'contributor', 'date', 'type', 'format', 'source', 'language',
        'coverage', 'rights',
    ]

    def __str__(self):
        return self.identifier

    def get_es_inner_data(self):
        """
        Returns a dictionary with field name > value with the required data
        to be stored in the Elasticsearch documents of related models.
        """
        data = {'identifier': self.identifier}
        add_if_not_empty(data, 'title', self.title)
        add_if_not_empty(data, 'date', self.date)
        add_if_not_empty(data, 'description', self.description)
        return data

    def get_display_data(self):
        """
        Returns a dictionary with display label > value from object fields,
        checking the enabled fields and the hide empty fields configuration.
        """
        hide_empty = self.hide_empty_fields()
        enabled_fields = self.enabled_fields()
        data = OrderedDict()
        for field_name in self.ORDERED_FIELDS:
            if field_name not in enabled_fields:
                continue
            value = getattr(self, field_name)
            if hide_empty and not value:
                continue
            field = self._meta.get_field(field_name)
            data[field.verbose_name] = value
        return data

    @classmethod
    def get_optional_fields(cls):
        """
        Returns a dictionary with optional fields name > verbose_name.
        """
        optional_fields = OrderedDict()
        for field_name in cls.ORDERED_FIELDS:
            field = cls._meta.get_field(field_name)
            if field.auto_created or field.name in cls.REQUIRED_FIELDS:
                continue
            optional_fields[field.name] = field.verbose_name
        return optional_fields

    @classmethod
    def enabled_fields(cls):
        """
        Returns a list with enabled field names based on
        `enabled_dc_fields` setting.
        """
        setting = Setting.objects.get(name='enabled_optional_dc_fields')
        return cls.REQUIRED_FIELDS + setting.value

    @classmethod
    def hide_empty_fields(cls):
        """
        Returns a boolean based on `hide_empty_dc_fields` setting.
        """
        setting = Setting.objects.get(name='hide_empty_dc_fields')
        return setting.value


class Collection(AbstractEsModel):
    link = models.URLField(_('finding aid'), blank=True)
    dc = models.OneToOneField(DublinCore, null=True, on_delete=models.SET_NULL)

    def __str__(self):
        return str(self.dc) or str(self.pk)

    es_doc = CollectionDoc

    def get_es_data(self):
        data = {
            '_id': self.pk,
        }

        if self.dc:
            data['dc'] = self.dc.get_es_inner_data()

        return data

    def get_es_data_for_files(self):
        data = {'id': self.pk}
        if self.dc:
            add_if_not_empty(data, 'identifier', self.dc.identifier)
            add_if_not_empty(data, 'title', self.dc.title)
        return data

    def requires_es_descendants_update(self):
        # No metadata needs to be updated in descandant DIPs
        count = DigitalFile.objects.filter(dip__collection__pk=self.pk).count()
        return count > 0

    def requires_es_descendants_delete(self):
        # There won't be DigitalFiles if there are no DIPs
        return self.dips.count() > 0


class DIP(AbstractEsModel):
    objectszip = models.FileField(_('objects zip file'))
    uploaded = models.DateTimeField(auto_now_add=True)
    collection = models.ForeignKey(
        Collection,
        related_name='dips',
        verbose_name=_('collection'),
        on_delete=models.CASCADE,
    )
    dc = models.OneToOneField(DublinCore, null=True, on_delete=models.SET_NULL)
    # The TaskResult created by 'django_celery_results' are not added
    # to the database when the import task is called. Therefore, a proper
    # model relation can't be made at that point. This field is used to
    # track the asynchronous result id from the task call, as that id
    # will match the `task_id` unique field from the TaskResult.
    import_task_id = models.CharField(max_length=255, null=True, unique=True)
    # Because a related TaskResult may not exist for two reasons: not created
    # yet or deleted (for example by a clean task), an extra field is needed
    # to know if there is an import in progress for the DIP. This field is also
    # used to track the import task status and it's set to `PENDING` when the
    # task is called from the `new_dip` view and to `SUCCESS` or `FAILURE` when
    # the task ends from within the task's `after_return` method.
    import_status = models.CharField(max_length=7, null=True)

    # Import statuses
    IMPORT_PENDING = 'PENDING'
    IMPORT_SUCCESS = 'SUCCESS'
    IMPORT_FAILURE = 'FAILURE'

    def __str__(self):
        return str(self.dc) or str(self.pk)

    @classmethod
    def import_statuses(cls):
        """Return dictionary with available statuses"""
        return {
            'PENDING': cls.IMPORT_PENDING,
            'SUCCESS': cls.IMPORT_SUCCESS,
            'FAILURE': cls.IMPORT_FAILURE,
        }

    es_doc = DIPDoc

    def get_es_data(self):
        data = {
            '_id': self.pk,
        }
        add_if_not_empty(data, 'import_status', self.import_status)
        add_if_not_empty(data, 'import_task_id', self.import_task_id)

        if self.dc:
            data['dc'] = self.dc.get_es_inner_data()

        if self.collection:
            data['collection'] = {'id': self.collection.pk}

        return data

    def get_es_data_for_files(self):
        data = {'id': self.pk}
        add_if_not_empty(data, 'import_status', self.import_status)
        if self.dc:
            add_if_not_empty(data, 'identifier', self.dc.identifier)
            add_if_not_empty(data, 'title', self.dc.title)
        return data

    def requires_es_descendants_update(self):
        return self.digital_files.count() > 0

    def requires_es_descendants_delete(self):
        return self.requires_es_descendants_update()

    def get_import_error_message(self):
        # Try to get error info from TaskResult
        try:
            result = TaskResult.objects.get(task_id=self.import_task_id)
            error = result.get_error_message()
        except TaskResult.DoesNotExist:
            error = gettext('A related task result could not be found.')
        return gettext(
            'An error occurred during the process executed to extract '
            'and parse the METS file. %(error_message)s Please, contact '
            'an administrator.' % {'error_message': error}
        )

    def is_visible_by_user(self, user):
        """
        Retrun `False` if there is an import pending for the DIP or if
        the import failed and the user is not an editor or an admin.
        Otherwise, return `True`.
        """
        return not (self.import_status == self.IMPORT_PENDING or (
            self.import_status == self.IMPORT_FAILURE and
            not user.is_editor()
        ))


class DigitalFile(AbstractEsModel):
    uuid = models.CharField(max_length=36, primary_key=True)
    filepath = models.TextField()
    fileformat = models.CharField(max_length=200)
    formatversion = models.CharField(max_length=200, blank=True, null=True)
    size_bytes = models.BigIntegerField()
    size_human = models.CharField(max_length=10, blank=True)
    # When support for time zones is enabled, Django stores datetime information
    # in UTC in the database, uses time-zone-aware datetime objects internally,
    # and translates them to the TIME_ZONE setting in templates and forms.
    datemodified = models.DateTimeField(blank=True, null=True)
    puid = models.CharField(max_length=200, blank=True)
    amdsec = models.CharField(max_length=12)
    hashtype = models.CharField(max_length=7)
    hashvalue = models.CharField(max_length=128)
    dip = models.ForeignKey(
        DIP,
        related_name='digital_files',
        on_delete=models.CASCADE,
    )

    def __str__(self):
        return self.uuid

    es_doc = DigitalFileDoc

    def get_es_data(self):
        data = {
            '_id': self.pk,
            'uuid': self.uuid,
            'filepath': self.filepath,
            'fileformat': self.fileformat,
            'size_bytes': self.size_bytes,
        }
        # Datetimes are saved as UTC in ES. In this case,
        # the TIME_ZONE setting is not considered.
        add_if_not_empty(data, 'datemodified', self.datemodified)

        # Ancestors data
        if self.dip:
            data['dip'] = self.dip.get_es_data_for_files()
            if self.dip.collection:
                data['collection'] = self.dip.collection.get_es_data_for_files()

        return data

    def requires_es_descendants_update(self):
        return False

    def requires_es_descendants_delete(self):
        return False


class PREMISEvent(models.Model):
    uuid = models.CharField(max_length=36, primary_key=True)
    eventtype = models.CharField(max_length=200, blank=True)
    datetime = models.CharField(max_length=50, blank=True)
    detail = models.TextField(blank=True, null=True)
    outcome = models.TextField(blank=True, null=True)
    detailnote = models.TextField(blank=True, null=True)
    digitalfile = models.ForeignKey(
        DigitalFile,
        related_name='premis_events',
        on_delete=models.CASCADE,
    )

    def __str__(self):
        return self.uuid


class Setting(models.Model):
    """
    Name/value pairs for application settings.

    A database-agnostic JSONField is used for the `value` field with auto
    encoding/decoding but without extended querying capabilities. If new
    settings are added and they are dictionaries where the order matters,
    change the field declaration to:

    `JSONField(load_kwargs={'object_pairs_hook': collections.OrderedDict})`
    """
    name = models.CharField(max_length=50, unique=True)
    value = JSONField(max_length=500)

    def __str__(self):
        return self.name
