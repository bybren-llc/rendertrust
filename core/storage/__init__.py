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

"""Object storage service package.

Provides an S3-compatible abstraction layer for file storage operations.
Supports MinIO (development), Cloudflare R2, and AWS S3 via boto3.
"""

from core.storage.config import StorageSettings, get_storage_settings
from core.storage.service import StorageService

__all__ = [
    "StorageService",
    "StorageSettings",
    "get_storage_settings",
]
