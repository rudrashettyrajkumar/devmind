"""DTOs for the GitHub read seam (E4, docs/01-solution-design.md §10).

Read-only. `gh` is used here for `issue view` and nothing else — no branch, no push,
no PR. That code does not exist until E10.
"""

from pydantic import BaseModel, ConfigDict

from devmind.core.enums import IssueState


class IssueRead(BaseModel):
    """One GitHub issue as parsed from `gh issue view --json number,title,body,labels,state`.

    `GitHubClient` flattens `labels` (a list of `{name, color, ...}` objects from `gh`)
    to their names and lower-cases `state` before constructing this.
    """

    model_config = ConfigDict(frozen=True)

    number: int
    title: str
    body: str = ""
    labels: tuple[str, ...] = ()
    state: IssueState
