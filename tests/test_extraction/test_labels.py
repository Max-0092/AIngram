# The GLiNER label set must cover the pipeline-domain entities F13 flagged
# (models, datasets, endpoints, pipeline stages, services) WITHOUT dropping any
# of the original general-purpose labels.
from aingram.storage.engine import StorageEngine
from aingram.worker import DEFAULT_ENTITY_TYPES, BackgroundWorker

EXISTING = {'person', 'organization', 'location', 'project', 'technology'}
NEW = {'model', 'dataset', 'endpoint', 'pipeline_stage', 'service'}


def test_default_labels_retain_existing():
    assert EXISTING <= set(DEFAULT_ENTITY_TYPES)


def test_default_labels_add_pipeline_domain_coverage():
    assert NEW <= set(DEFAULT_ENTITY_TYPES)


def test_default_labels_have_no_duplicates():
    assert len(DEFAULT_ENTITY_TYPES) == len(set(DEFAULT_ENTITY_TYPES))


def test_worker_default_uses_the_constant(tmp_path):
    eng = StorageEngine(str(tmp_path / 't.db'))
    w = BackgroundWorker(eng, extractor=object())  # extractor unused for label config
    assert set(w._entity_types) == set(DEFAULT_ENTITY_TYPES)
    eng.close()
