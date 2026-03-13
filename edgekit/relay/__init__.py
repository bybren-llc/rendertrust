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

"""Edge relay client: WebSocket client for connecting to the relay server.

Provides :class:`RelayClient` for edge nodes to establish authenticated
WebSocket connections to the gateway relay, receive job assignments,
send acknowledgements and status updates, and maintain heartbeat connectivity
with automatic reconnection and exponential backoff.
"""

from edgekit.relay.client import RelayClient

__all__ = ["RelayClient"]
