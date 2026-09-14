"""Project leases shared by API, CLI and SDK; no background queue required."""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from functools import wraps
import inspect
import time
import uuid


class ProjectBusy(RuntimeError):
    pass


class LeaseLost(ProjectBusy):
    pass


class NeedsClarification(ValueError):
    pass


class QualityFailed(ValueError):
    pass


class SubmissionUncertain(RuntimeError):
    pass


# Only the owning asyncio task may inherit an execution lease.
lease_context = ContextVar("movie_lease", default=None)
evaluation_context = ContextVar("movie_evaluation", default="full")
metrics_context = ContextVar("movie_metrics", default=None)


def current_task():
    try:
        return asyncio.current_task()
    except RuntimeError:
        return None


def owned(db, pid):
    entry = lease_context.get()
    return entry and entry[:2] == (str(db.db_path), pid) and entry[3] is current_task()


def exclusive(fn):
    """Nested calls reuse a lease; independent callers conflict, never interleave."""
    if not inspect.iscoroutinefunction(fn):
        @wraps(fn)
        def sync(self, project_id, *args, **kwargs):
            if owned(self.db, project_id):
                self.db.assert_lease(project_id, lease_context.get()[2])
                return fn(self, project_id, *args, **kwargs)
            owner = uuid.uuid4().hex
            self.db.acquire_lease(project_id, owner)
            token = lease_context.set((str(self.db.db_path), project_id, owner, current_task()))
            try:
                return fn(self, project_id, *args, **kwargs)
            finally:
                lease_context.reset(token)
                self.db.release_lease(project_id, owner)
        return sync

    @wraps(fn)
    async def run(self, project_id, *args, **kwargs):
        if owned(self.db, project_id):
            self.db.assert_lease(project_id, lease_context.get()[2])
            return await fn(self, project_id, *args, **kwargs)
        owner = uuid.uuid4().hex
        self.db.acquire_lease(project_id, owner)
        token = lease_context.set((str(self.db.db_path), project_id, owner, current_task()))
        async def renew():
            lease_context.set(None)
            while True:
                await asyncio.sleep(15)
                self.db.renew_lease(project_id, owner)
        heartbeat = asyncio.create_task(renew())
        try:
            result = await fn(self, project_id, *args, **kwargs)
            self.db.assert_lease(project_id, owner)
            return result
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            lease_context.reset(token)
            self.db.release_lease(project_id, owner)
    return run
