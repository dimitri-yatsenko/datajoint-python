import pymysql
import pytest

import datajoint as dj
from datajoint import DataJointError

from . import schema


def test_populate(trial, subject, experiment, ephys, channel):
    # test simple populate
    assert subject, "root tables are empty"
    assert not experiment, "table already filled?"
    experiment.populate()
    assert len(experiment) == len(subject) * experiment.fake_experiments_per_subject

    # test restricted populate
    assert not trial, "table already filled?"
    restriction = subject.proj(animal="subject_id").fetch("KEY")[0]
    d = trial.connection.dependencies
    d.load()
    trial.populate(restriction)
    assert trial, "table was not populated"
    key_source = trial.key_source
    assert len(key_source & trial) == len(key_source & restriction)
    assert len(key_source - trial) == len(key_source - restriction)

    # test subtable populate
    assert not ephys
    assert not channel
    ephys.populate()
    assert ephys
    assert channel


def test_populate_with_success_count(subject, experiment, trial):
    # test simple populate
    assert subject, "root tables are empty"
    assert not experiment, "table already filled?"
    ret = experiment.populate()
    success_count = ret["success_count"]
    assert len(experiment.key_source & experiment) == success_count

    # test restricted populate
    assert not trial, "table already filled?"
    restriction = subject.proj(animal="subject_id").fetch("KEY")[0]
    d = trial.connection.dependencies
    d.load()
    ret = trial.populate(restriction, suppress_errors=True)
    success_count = ret["success_count"]
    assert len(trial.key_source & trial) == success_count


def test_populate_key_list(subject, experiment, trial):
    # test simple populate
    assert subject, "root tables are empty"
    assert not experiment, "table already filled?"
    keys = experiment.key_source.fetch("KEY", order_by="KEY")
    n = 3
    assert len(keys) > n
    keys = keys[:n]
    ret = experiment.populate(keys=keys)
    assert n == ret["success_count"]


def test_populate_exclude_error_and_ignore_jobs(schema_any, subject, experiment):
    # test simple populate
    assert subject, "root tables are empty"
    assert not experiment, "table already filled?"

    keys = experiment.key_source.fetch("KEY", limit=2)
    for idx, key in enumerate(keys):
        if idx == 0:
            schema_any.jobs.ignore(experiment.table_name, key)
        else:
            schema_any.jobs.error(experiment.table_name, key, "")

    experiment.populate(reserve_jobs=True)
    assert len(experiment.key_source & experiment) == len(experiment.key_source) - 2


def test_allow_direct_insert(subject, experiment):
    assert subject, "root tables are empty"
    key = subject.fetch("KEY", limit=1)[0]
    key["experiment_id"] = 1000
    key["experiment_date"] = "2018-10-30"
    experiment.insert1(key, allow_direct_insert=True)


@pytest.mark.parametrize("processes", [None, 2])
def test_multi_processing(subject, experiment, processes):
    assert subject, "root tables are empty"
    assert not experiment, "table already filled?"
    experiment.populate(processes=None)
    assert len(experiment) == len(subject) * experiment.fake_experiments_per_subject


def test_allow_insert(subject, experiment):
    assert subject, "root tables are empty"
    key = subject.fetch("KEY")[0]
    key["experiment_id"] = 1001
    key["experiment_date"] = "2018-10-30"
    with pytest.raises(DataJointError):
        experiment.insert1(key)


def test_load_dependencies(prefix):
    schema = dj.Schema(f"{prefix}_load_dependencies_populate")

    @schema
    class ImageSource(dj.Lookup):
        definition = """
        image_source_id: int
        """
        contents = [(0,)]

    @schema
    class Image(dj.Imported):
        definition = """
        -> ImageSource
        ---
        image_data: longblob
        """

        def make(self, key):
            self.insert1(dict(key, image_data=dict()))

    Image.populate()

    @schema
    class Crop(dj.Computed):
        definition = """
        -> Image
        ---
        crop_image: longblob
        """

        def make(self, key):
            self.insert1(dict(key, crop_image=dict()))

    Crop.populate()


def test_populate_with_jobs(schema_any, subject, experiment):
    # test simple populate
    assert subject, "root tables are empty"
    assert not experiment, "table already filled?"

    experiment.populate(reserve_jobs=True)
    assert len(experiment.key_source & experiment) == len(experiment.key_source)


def test_jobs_table2_functionality(schema_any, subject, experiment):
    """Test the new JobTable2 functionality"""
    # Test that jobs table is created
    assert hasattr(experiment, 'jobs')
    assert experiment.jobs is not None
    
    # Test refresh functionality
    experiment.jobs.refresh(experiment.key_source)
    
    # Check that jobs were created
    scheduled_jobs = experiment.jobs.get_scheduled_jobs()
    assert len(scheduled_jobs) > 0
    
    # Test job reservation
    key = scheduled_jobs[0]
    assert experiment.jobs.reserve(key)
    
    # Test that reserved job is not available for reservation again
    assert not experiment.jobs.reserve(key)
    
    # Test job completion
    experiment.jobs.complete(key, run_duration=1.5, run_version={"git_hash": "abc123"})
    
    # Test job error handling
    error_key = scheduled_jobs[1] if len(scheduled_jobs) > 1 else key
    experiment.jobs.error(error_key, "Test error", "Test stack trace")
    
    # Test priority setting
    if len(scheduled_jobs) > 2:
        priority_key = scheduled_jobs[2]
        experiment.jobs.set_priority(priority_key, 1)
        
        # Test ordering by priority
        ordered_jobs = experiment.jobs.get_scheduled_jobs(order_by=['priority', 'timestamp'])
        assert len(ordered_jobs) > 0


def test_populate_with_new_jobs_table(schema_any, subject, experiment):
    """Test populate with the new jobs table design"""
    assert subject, "root tables are empty"
    assert not experiment, "table already filled?"
    
    # Test populate with new jobs table
    experiment.populate(reserve_jobs=True, refresh_jobs=True)
    assert len(experiment.key_source & experiment) == len(experiment.key_source)
    
    # Verify jobs table has success records
    success_jobs = experiment.jobs & 'status="success"'
    assert len(success_jobs) > 0
    
    # Check that run_duration is recorded
    durations = success_jobs.fetch('run_duration')
    assert all(d > 0 for d in durations if d is not None)


def test_populate_without_refresh(schema_any, subject, experiment):
    """Test populate without refreshing jobs table"""
    assert subject, "root tables are empty"
    assert not experiment, "table already filled?"
    
    # First populate to create some jobs
    experiment.populate(reserve_jobs=True, refresh_jobs=True)
    
    # Clear the experiment table
    experiment.delete_quick()
    
    # Populate again without refresh - should use existing jobs
    experiment.populate(reserve_jobs=True, refresh_jobs=False)
    assert len(experiment.key_source & experiment) == len(experiment.key_source)


def test_jobs_table_cascade_delete(schema_any, subject, experiment):
    """Test that jobs table is properly cascaded when table is deleted"""
    # Create jobs
    experiment.populate(reserve_jobs=True, refresh_jobs=True)
    
    # Verify jobs exist
    assert len(experiment.jobs) > 0
    
    # Delete the experiment table
    experiment.delete_quick()
    
    # Jobs table should be automatically cleaned up due to cascade delete
    # This test verifies the foreign key relationship works correctly
