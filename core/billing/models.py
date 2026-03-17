# Copyright 2026 ByBren, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Billing domain models for job pricing configuration.

Provides the JobPricing model for per-job-type credit pricing.
Administrators can configure custom pricing per job type; the
UsageService falls back to hardcoded defaults when no DB row exists.
"""

from decimal import Decimal

from sqlalchemy import Boolean, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from core.database import BaseModel


class JobPricing(BaseModel):
    """Per-job-type credit pricing configuration.

    Attributes:
        job_type: Unique job type identifier (e.g. 'render', 'inference').
        credits_per_unit: Number of credits charged per unit of work.
        unit_type: Unit of measurement (default: 'per_job').
        is_active: Whether this pricing rule is currently active.
    """

    __tablename__ = "job_pricing"
    __table_args__ = (Index("ix_job_pricing_job_type", "job_type", unique=True),)

    job_type: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
    )
    credits_per_unit: Mapped[Decimal] = mapped_column(
        Numeric(12, 4),
        nullable=False,
    )
    unit_type: Mapped[str] = mapped_column(
        String(50),
        default="per_job",
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<JobPricing(id={self.id}, job_type={self.job_type}, "
            f"credits_per_unit={self.credits_per_unit})>"
        )
