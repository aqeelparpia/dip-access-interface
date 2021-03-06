from django.test import TestCase
from unittest.mock import patch

from dips.models import Collection, DIP, DublinCore


class DcDeletionTests(TestCase):
    @patch('elasticsearch_dsl.DocType.save')
    def setUp(self, patch):
        dc = DublinCore.objects.create(identifier='1')
        self.collection = Collection.objects.create(dc=dc)
        dc = DublinCore.objects.create(identifier='A')
        self.dip = DIP.objects.create(
            dc=dc,
            collection=self.collection,
            objectszip='/path/to/fake.zip',
        )

    @patch('elasticsearch.client.Elasticsearch.delete')
    @patch('dips.models.celery_app.send_task')
    def test_dip_deletion(self, patch, patch_2):
        dc_count = DublinCore.objects.filter(identifier='A').count()
        self.assertEqual(dc_count, 1)
        self.dip.delete()
        dc_count = DublinCore.objects.filter(identifier='A').count()
        self.assertEqual(dc_count, 0)

    @patch('elasticsearch.client.Elasticsearch.delete')
    @patch('dips.models.celery_app.send_task')
    def test_collection_deletion(self, patch, patch_2):
        dc_count = DublinCore.objects.all().count()
        self.assertEqual(dc_count, 2)
        self.collection.delete()
        # It should also delete the DIP DublinCore
        dc_count = DublinCore.objects.all().count()
        self.assertEqual(dc_count, 0)
