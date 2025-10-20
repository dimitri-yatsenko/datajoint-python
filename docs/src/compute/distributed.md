# Distributed Computing

## Job reservations

Running `populate` on the same table on multiple computers will causes them to attempt
to compute the same data all at once.
This will not corrupt the data since DataJoint will reject any duplication.
One solution could be to cause the different computing nodes to populate the tables in
random order.
This would reduce some collisions but not completely prevent them.

To allow efficient distributed computing, DataJoint provides a built-in job reservation
process.
When `dj.Computed` tables are auto-populated using job reservation, a record of each
ongoing computation is kept in a schema-wide `jobs` table, which is used internally by
DataJoint to coordinate the auto-population effort among multiple computing processes.

Job reservations are activated by setting the keyword argument `reserve_jobs=True` in
`populate` calls.

With job management enabled, the `make` method of each table class will also consult
the `jobs` table for reserved jobs as part of determining the next record to compute
and will create an entry in the `jobs` table as part of the attempt to compute the
resulting record for that key.
If the operation is a success, the record is removed.
In the event of failure, the job reservation entry is updated to indicate the details
of failure.
Using this simple mechanism, multiple processes can participate in the auto-population
effort without duplicating computational effort, and any errors encountered during the
course of the computation can be individually inspected to determine the cause of the
issue.

As part of DataJoint, the jobs table can be queried using native DataJoint syntax. For
example, to list the jobs currently being run:

```python
In [1]: schema.jobs
Out[1]:
*table_name    *key_hash      status       error_message  user           host           pid       connection_id  timestamp      key        error_stack
```

## Enhanced Job Management (JobTable2)

DataJoint now provides an enhanced job management system that addresses scalability
limitations of the original jobs table. The new system creates individual job tables
for each computed table, providing better performance and more detailed job tracking.

### Key Improvements

1. **Per-table job tables**: Each computed table gets its own job table with the same
   primary key structure, eliminating the need for key hashing.

2. **Enhanced status tracking**: Jobs can have statuses including `scheduled`, `reserved`,
   `error`, `ignore`, and `success`.

3. **Priority system**: Jobs can be assigned priorities for better scheduling control.

4. **Performance metrics**: Job completion times and version information are tracked.

5. **Automatic refresh**: Jobs tables can be automatically synchronized with key sources.

### Using the Enhanced Job System

To use the enhanced job system, simply call `populate()` with `reserve_jobs=True`:

```python
# This will automatically use the new job table design
MyComputedTable.populate(reserve_jobs=True)
```

### Accessing Job Tables

Each AutoPopulate table now has a `jobs` property that provides access to its job table:

```python
# Access the job table for a specific computed table
jobs_table = MyComputedTable.jobs

# Query job status
scheduled_jobs = jobs_table & 'status="scheduled"'
successful_jobs = jobs_table & 'status="success"'
failed_jobs = jobs_table & 'status="error"'

# Get job statistics
total_jobs = len(jobs_table)
completed_jobs = len(successful_jobs)
failed_jobs = len(failed_jobs)
```

### Job Table Schema

The new job tables have the following structure:

```sql
-- Primary key matches the computed table
PRIMARY_KEY_ATTR1 :varchar(255)
PRIMARY_KEY_ATTR2 :varchar(255)
...
---
status :enum('scheduled','reserved','error','ignore','success')
priority=3 :tinyint  # Lower values = higher priority
error_message="" :varchar(2047)
error_stack=null :mediumblob
run_duration=null :float  # Duration in seconds
run_version=null :json  # Version information
user="" :varchar(255)
host="" :varchar(255)
pid=0 :int unsigned
connection_id=0 :bigint unsigned
timestamp=CURRENT_TIMESTAMP :timestamp
```

### Job Management Operations

```python
# Refresh jobs table with current key source
MyComputedTable.jobs.refresh(MyComputedTable.key_source)

# Get scheduled jobs with custom ordering
jobs = MyComputedTable.jobs.get_scheduled_jobs(
    limit=10, 
    order_by=['priority', 'timestamp']
)

# Set job priority
MyComputedTable.jobs.set_priority(job_key, priority=1)

# Manually mark job as ignored
MyComputedTable.jobs.ignore(job_key)
```

### Populate Options

The `populate()` method now supports additional options for job management:

```python
MyComputedTable.populate(
    reserve_jobs=True,      # Enable job reservation
    refresh_jobs=True,      # Refresh jobs table before populating (default)
    order="original",       # Job processing order
    limit=100,             # Limit number of jobs to process
)
```

### Backward Compatibility

The new job system is fully backward compatible. Existing code using `schema.jobs` will
continue to work, and the new system will automatically be used when `reserve_jobs=True`
is specified.

## Legacy Job Management

The original schema-wide jobs table is still available for backward compatibility:

```python
# Access the legacy jobs table
legacy_jobs = schema.jobs

# Query jobs by table name
table_jobs = legacy_jobs & {'table_name': 'MyComputedTable'}

# Query by status
error_jobs = legacy_jobs & 'status="error"'
```

As part of DataJoint, the jobs table can be queried using native DataJoint syntax. For
example, to list the jobs currently being run:

```python
In [1]: schema.jobs
Out[1]:
*table_name    *key_hash      status       error_message  user           host           pid       connection_id  timestamp      key        error_stack
```

### Job Status Management

When a job fails, it remains in the jobs table with status "error" to prevent the
record from being processed during subsequent auto-population calls.
Inspecting the job record for failure details can proceed much like any other DataJoint
query.

For example, given the above table, errors can be inspected as follows:

```python
In [3]: (schema.jobs & 'status="error"' ).fetch(as_dict=True)
Out[3]:
[OrderedDict([('table_name', '__job_results'),
               ('key_hash', 'c81e728d9d4c2f636f067f89cc14862c'),
               ('status', 'error'),
               ('key', rec.array([(2,)],
                         dtype=[('id', 'O')])),
               ('error_message', 'KeyboardInterrupt'),
               ('error_stack', None),
               ('user', 'datajoint@localhost'),
               ('host', 'localhost'),
               ('pid', 15571),
               ('connection_id', 59),
               ('timestamp', datetime.datetime(2017, 9, 4, 15, 3, 53))])]
```

This particular error occurred when processing the record with ID `2`, resulted from a
`KeyboardInterrupt`, and has no additional
error trace.

After any system or code errors have been resolved, the table can simply be cleaned of
errors and the computation rerun.

For example:

```python
In [4]: (schema.jobs & 'status="error"' ).delete()
```

In some cases, it may be preferable to inspect the jobs table records using populate
keys.
Since job keys are hashed and stored as a blob in the jobs table to support the varying
types of keys, we need to query using the key hash instead of simply using the raw key
data.

This can be done by using `dj.key_hash` to convert the key as follows:

```python
In [4]: jk = {'table_name': JobResults.table_name, 'key_hash' : dj.key_hash({'id': 2})}

In [5]: schema.jobs & jk
Out[5]:
*table_name    *key_hash      status     key        error_message  error_stac user           host      pid        connection_id  timestamp
+------------+ +------------+ +--------+ +--------+ +------------+ +--------+ +------------+ +-------+ +--------+ +------------+ +------------+
```

The job can then be removed from the jobs table to allow it to be processed again:

```python
In [6]: (schema.jobs & jk).delete()
```

And the jobs table can be queried again to confirm the job has been removed:

```python
In [7]: schema.jobs & jk
Out[7]:
*table_name    *key_hash      status     key        error_message  error_stac user           host      pid        connection_id  timestamp
+------------+ +------------+ +--------+ +--------+ +------------+ +--------+ +------------+ +-------+ +--------+ +------------+ +------------+
```
