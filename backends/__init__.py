from core.reviewer import Reviewer
from backends.chromium_gerrit import ChromiumGerritReviewer
from backends.local import LocalReviewer
from backends.github import GitHubReviewer

def get_reviewer(target: str, gemini_client, model_name: str, mock: bool) -> Reviewer:
    reviewers = [
        LocalReviewer,
        GitHubReviewer,
        ChromiumGerritReviewer,  # Fallback to this for gerrit URLs/IDs
    ]
    
    for reviewer_cls in reviewers:
        if reviewer_cls.handles_target(target):
            return reviewer_cls(gemini_client, model_name, mock)
    
    raise ValueError(f"No reviewer backend found for target: {target}")
