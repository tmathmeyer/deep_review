from hosts.host import Host

from hosts.impl.local import Local
from hosts.impl.github import GitHub
from hosts.impl.gerrit import Gerrit


def GetCodeHosts() -> [Host]:
  return [
    Local,
    GitHub,
    Gerrit,
  ]
