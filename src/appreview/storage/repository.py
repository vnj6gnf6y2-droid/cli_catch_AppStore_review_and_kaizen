"""Repository layer for database access."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from appreview.storage.models import ClassificationOrm, ClusterOrm, ReviewOrm, RunOrm


class ReviewRepository:
    """Data access layer for reviews."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_reviews(self, reviews: list[dict]) -> int:  # type: ignore[type-arg]
        """Insert reviews, ignoring duplicates (idempotent).

        Args:
            reviews: List of dicts with review fields.

        Returns:
            Number of newly inserted reviews.
        """
        if not reviews:
            return 0

        inserted = 0
        # Batch in chunks of 100
        for i in range(0, len(reviews), 100):
            batch = reviews[i : i + 100]
            stmt = sqlite_insert(ReviewOrm).values(batch)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["source", "id"]
            )
            result = await self._session.execute(stmt)
            inserted += result.rowcount or 0

        return inserted

    async def get_review_ids(self, source: str, app_identifier: str) -> set[str]:
        """Get all known review IDs for a given source and app.

        Args:
            source: 'app_store' or 'google_play'.
            app_identifier: app_id or package_name.

        Returns:
            Set of review IDs.
        """
        stmt = select(ReviewOrm.id).where(
            ReviewOrm.source == source,
            ReviewOrm.app_identifier == app_identifier,
        )
        result = await self._session.execute(stmt)
        return {row[0] for row in result.all()}

    async def get_unclassified_reviews(
        self,
        source: str,
        app_identifier: str,
    ) -> Sequence[ReviewOrm]:
        """Get reviews that haven't been classified yet.

        Args:
            source: 'app_store' or 'google_play'.
            app_identifier: app_id or package_name.

        Returns:
            List of unclassified ReviewOrm instances.
        """
        classified_ids_stmt = select(ClassificationOrm.review_id).where(
            ClassificationOrm.review_source == source
        )
        classified_result = await self._session.execute(classified_ids_stmt)
        classified_ids = {row[0] for row in classified_result.all()}

        stmt = select(ReviewOrm).where(
            ReviewOrm.source == source,
            ReviewOrm.app_identifier == app_identifier,
            ReviewOrm.id.notin_(classified_ids) if classified_ids else ReviewOrm.id.isnot(None),
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_reviews_for_run(
        self,
        source: str,
        app_identifier: str,
        since: datetime | None = None,
    ) -> Sequence[ReviewOrm]:
        """Get reviews for analysis, optionally filtered by date.

        Args:
            source: 'app_store' or 'google_play'.
            app_identifier: app_id or package_name.
            since: Only return reviews created after this datetime.

        Returns:
            List of ReviewOrm instances.
        """
        stmt = select(ReviewOrm).where(
            ReviewOrm.source == source,
            ReviewOrm.app_identifier == app_identifier,
        )
        if since:
            stmt = stmt.where(ReviewOrm.created_at >= since)
        stmt = stmt.order_by(ReviewOrm.created_at.desc())
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def count_reviews(self, source: str, app_identifier: str) -> int:
        """Count total reviews for an app.

        Args:
            source: 'app_store' or 'google_play'.
            app_identifier: app_id or package_name.

        Returns:
            Total review count.
        """
        stmt = select(ReviewOrm).where(
            ReviewOrm.source == source,
            ReviewOrm.app_identifier == app_identifier,
        )
        result = await self._session.execute(stmt)
        return len(result.scalars().all())


class ClassificationRepository:
    """Data access layer for classifications."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_classifications(
        self, classifications: list[dict]  # type: ignore[type-arg]
    ) -> None:
        """Save classification results in batch.

        Args:
            classifications: List of dicts with classification fields.
        """
        if not classifications:
            return

        for i in range(0, len(classifications), 100):
            batch = classifications[i : i + 100]
            for item in batch:
                self._session.add(ClassificationOrm(**item))

    async def get_classifications_for_review(
        self, review_source: str, review_id: str
    ) -> Sequence[ClassificationOrm]:
        """Get all classifications for a specific review.

        Args:
            review_source: 'app_store' or 'google_play'.
            review_id: Review ID.

        Returns:
            List of ClassificationOrm instances.
        """
        stmt = select(ClassificationOrm).where(
            ClassificationOrm.review_source == review_source,
            ClassificationOrm.review_id == review_id,
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_negative_reviews_by_category(
        self,
        source: str,
        app_identifier: str,
        category: str,
    ) -> Sequence[ReviewOrm]:
        """Get negative reviews for a given category (for clustering).

        Args:
            source: 'app_store' or 'google_play'.
            app_identifier: app_id or package_name.
            category: Category to filter by.

        Returns:
            List of ReviewOrm instances with negative sentiment.
        """
        stmt = (
            select(ReviewOrm)
            .join(
                ClassificationOrm,
                (ClassificationOrm.review_source == ReviewOrm.source)
                & (ClassificationOrm.review_id == ReviewOrm.id),
            )
            .where(
                ReviewOrm.source == source,
                ReviewOrm.app_identifier == app_identifier,
                ClassificationOrm.category == category,
                ClassificationOrm.sentiment == "negative",
            )
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()


class ClusterRepository:
    """Data access layer for clusters."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_clusters(self, clusters: list[dict]) -> None:  # type: ignore[type-arg]
        """Save cluster results.

        Args:
            clusters: List of dicts with cluster fields.
        """
        for item in clusters:
            if "id" not in item:
                item["id"] = str(uuid.uuid4())
            self._session.add(ClusterOrm(**item))

    async def get_clusters_for_run(self, run_id: str) -> Sequence[ClusterOrm]:
        """Get all clusters for a specific run.

        Args:
            run_id: Run UUID.

        Returns:
            List of ClusterOrm instances.
        """
        stmt = select(ClusterOrm).where(ClusterOrm.run_id == run_id)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def delete_clusters_for_run(self, run_id: str) -> None:
        """Delete all clusters for a run (for re-generation).

        Args:
            run_id: Run UUID.
        """
        stmt = delete(ClusterOrm).where(ClusterOrm.run_id == run_id)
        await self._session.execute(stmt)


class RunRepository:
    """Data access layer for run history."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_run(self, app_name: str | None = None) -> RunOrm:
        """Create a new run record.

        Args:
            app_name: Optional app name for this run.

        Returns:
            Newly created RunOrm instance.
        """
        run = RunOrm(
            id=str(uuid.uuid4()),
            started_at=datetime.now(tz=timezone.utc),
            status="running",
            app_name=app_name,
        )
        self._session.add(run)
        await self._session.flush()
        return run

    async def update_run(
        self,
        run_id: str,
        **kwargs: object,
    ) -> None:
        """Update run fields.

        Args:
            run_id: Run UUID.
            **kwargs: Fields to update.
        """
        stmt = select(RunOrm).where(RunOrm.id == run_id)
        result = await self._session.execute(stmt)
        run = result.scalar_one_or_none()
        if run:
            for key, value in kwargs.items():
                setattr(run, key, value)

    async def get_run(self, run_id: str) -> RunOrm | None:
        """Get a specific run by ID.

        Args:
            run_id: Run UUID.

        Returns:
            RunOrm instance or None.
        """
        stmt = select(RunOrm).where(RunOrm.id == run_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_runs(self, limit: int = 20) -> Sequence[RunOrm]:
        """List recent runs.

        Args:
            limit: Maximum number of runs to return.

        Returns:
            List of RunOrm instances, newest first.
        """
        stmt = select(RunOrm).order_by(RunOrm.started_at.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return result.scalars().all()
