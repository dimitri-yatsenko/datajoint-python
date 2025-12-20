import json
import os
import platform

from .errors import DuplicateError
from .heading import Heading
from .table import Table

ERROR_MESSAGE_LENGTH = 2047
TRUNCATION_APPENDIX = "...truncated"


class Job(Table):
    """
    Job table tracking jobs for individual computed tables.
    Each computed table gets its own jobs table with the same primary key structure.
    """

    def __init__(self, computed_table: Table):
        """
        Initialize a job table for a specific computed table.
        :param computed_table: AutoPopulate instance
        """
        self.database = computed_table.database
        self._connection = computed_table.connection

        # Create table name for jobs table
        self._table_name = f"~{computed_table.name}_job"
        self._support = [self.full_table_name]

        self._heading = Heading(
            table_info=dict(
                conn=computed_table.connection,
                database=computed_table.database,
                table_name=self.table_name,
                context=None,
            )
        )

        self._definition = f"# job table for {self.computed_table.full_table_name}\n"

        # add primary foreign key references to parent tables to the definition
        parents = computed_table.parents(
            as_objects=False, primary_key=True, foreign_key_info=True
        )
        for parent_name, fk_props in parents:
            if not fk_props["aliased"]:
                # simple foreign key
                self._definition += f"->{parent_name}\n"
            else:
                # projected foreign key
                self._definition += "->{parent_name}.proj({proj_list})\n".format(
                    parent_name=parent_name,
                    proj_list=",".join(
                        '{}="{}"'.format(attr, ref)
                        for attr, ref in fk_props["attr_map"].items()
                        if ref != attr
                    ),
                )
        self._definition += """
        ---
        status :enum('scheduled','reserved','error','ignore')  # job status
        priority=3 :tinyint  # job priority (smaller numbers mean higher priority)
        error_message="" :varchar({ERROR_MESSAGE_LENGTH})  # error message if failed
        error_stack=null :mediumblob  # error stack if failed
        run_duration=null :float  # run duration in seconds
        run_version=null :json  # code/environment version info
        user="" :varchar(255)  # database user
        host="" :varchar(255)  # system hostname
        pid=0 :int unsigned  # system process id
        connection_id=0 :bigint unsigned  # connection_id()
        timestamp=CURRENT_TIMESTAMP :timestamp  # automatic timestamp
        """

        if not self.is_declared:
            self.declare()
        self._user = self.connection.get_user()

    @property
    def definition(self):
        return self._definition

    @property
    def table_name(self):
        return self._jobs_table_name

    def delete(self):
        """bypass interactive prompts and dependencies"""
        self.delete_quick()

    def drop(self):
        """bypass interactive prompts and dependencies"""
        self.drop_quick()

    def refresh(self, key_source):
        """
        Refresh the jobs table by syncing with key_source.
        Removes jobs that are no longer in key_source and adds new ones.

        :param key_source: QueryExpression that defines available jobs
        """
        # Get current jobs that should be preserved (reserved, error, ignore)
        preserve_statuses = ("reserved", "error", "ignore")
        existing_jobs = (self & f"status in {preserve_statuses}").fetch("KEY")

        # Get all keys from key_source
        available_keys = key_source.fetch("KEY")

        # Remove jobs that are no longer in key_source
        for job_key in existing_jobs:
            if job_key not in available_keys:
                (self & job_key).delete_quick()

        # Add new jobs that aren't already in the table
        existing_all = self.fetch("KEY")
        for key in available_keys:
            if key not in existing_all:
                self.insert1(dict(**key, status="scheduled", priority=3))

    def reserve(self, key):
        """
        Reserve a job for computation.

        :param key: the dict of the job's primary key
        :return: True if reserved job successfully. False = the job is already taken
        """
        job = dict(
            **key,
            status="reserved",
            host=platform.node(),
            pid=os.getpid(),
            connection_id=self.connection.connection_id,
            user=self._user,
        )
        try:
            self.insert1(job, replace=True, ignore_extra_fields=True)
        except DuplicateError:
            return False
        return True

    def ignore(self, key):
        """
        Set a job to be ignored for computation.

        :param key: the dict of the job's primary key
        :return: True if ignore job successfully. False = the job is already taken
        """
        job = dict(
            **key,
            status="ignore",
            host=platform.node(),
            pid=os.getpid(),
            connection_id=self.connection.connection_id,
            user=self._user,
        )
        try:
            self.insert1(job, replace=True, ignore_extra_fields=True)
        except DuplicateError:
            return False
        return True

    def complete(self, key, run_duration=None, run_version=None):
        """
        Mark a job as completed successfully.

        :param key: the dict of the job's primary key
        :param run_duration: duration of the job in seconds
        :param run_version: version information (e.g., git commit hash)
        """
        job = dict(
            **key,
            status="success",
            run_duration=run_duration,
            run_version=json.dumps(run_version) if run_version else None,
            host=platform.node(),
            pid=os.getpid(),
            connection_id=self.connection.connection_id,
            user=self._user,
        )
        self.insert1(job, replace=True, ignore_extra_fields=True)

    def error(self, key, error_message, error_stack=None):
        """
        Log an error for a job.

        :param key: the dict of the job's primary key
        :param error_message: string error message
        :param error_stack: stack trace
        """
        if len(error_message) > ERROR_MESSAGE_LENGTH:
            error_message = (
                error_message[: ERROR_MESSAGE_LENGTH - len(TRUNCATION_APPENDIX)]
                + TRUNCATION_APPENDIX
            )

        job = dict(
            **key,
            status="error",
            error_message=error_message,
            error_stack=error_stack,
            host=platform.node(),
            pid=os.getpid(),
            connection_id=self.connection.connection_id,
            user=self._user,
        )
        self.insert1(job, replace=True, ignore_extra_fields=True)

    def get_scheduled_jobs(self, limit=None, order_by=None):
        """
        Get scheduled jobs, optionally ordered and limited.

        :param limit: maximum number of jobs to return
        :param order_by: ordering criteria (e.g., ['priority', 'timestamp'])
        :return: list of job keys
        """
        query = self & 'status="scheduled"'

        if order_by:
            if isinstance(order_by, str):
                order_by = [order_by]
            query = query.fetch(order_by=order_by)
        else:
            # Default ordering: priority (ascending), then timestamp (ascending)
            query = query.fetch(order_by=["priority", "timestamp"])

        if limit:
            query = query[:limit]

        return query.fetch("KEY")

    def set_priority(self, key, priority):
        """
        Set the priority of a job.

        :param key: the dict of the job's primary key
        :param priority: priority value (lower = higher priority)
        """
        self.update1(dict(**key, priority=priority))
