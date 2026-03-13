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

"""EdgeKit CLI -- command-line interface for edge node management.

Provides ``edgekit register`` and ``edgekit status`` commands for
node registration, key generation, and health monitoring.

Entry point: ``edgekit`` (defined in pyproject.toml [project.scripts]).
"""

from __future__ import annotations

import click

from edgekit.cli.register import register
from edgekit.cli.status import status


@click.group()
@click.version_option(version="0.1.0", prog_name="edgekit")
def cli() -> None:
    """EdgeKit -- RenderTrust edge node management CLI."""


cli.add_command(register)
cli.add_command(status)


def main() -> None:
    """CLI entry point."""
    cli()
