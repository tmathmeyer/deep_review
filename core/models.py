"""
Data structures representing the inputs and outputs of the review system.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ChangeInfo:
  cl_id: str
  host: str
  project: str = ""
  branch: str = ""
  status: str = ""
  patch_set: str = ""
  author_name: str = ""
  author_email: str = ""
  created: str = ""
  updated: str = ""
  subject: str = ""
  message: str = ""
  commit_url: str = ""
  gitiles_link: str = ""


@dataclass
class AnalysisResult:
  summary: str
  extra_context_files: List[str] = field(default_factory=list)


@dataclass
class AgentReview:
  agent_name: str
  response_text: Optional[str]
  status: str  # e.g., 'Done', 'Failed'
  error_message: Optional[str] = None
