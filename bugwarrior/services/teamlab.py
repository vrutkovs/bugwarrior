import json
import urllib
import urllib2

from twiggy import log

from bugwarrior.config import die, get_service_password
from bugwarrior.services import Issue, IssueService


class TeamLabClient(object):
    def __init__(self, hostname, verbose=False):
        self.hostname = hostname
        self.verbose = verbose
        self.token = None

    def authenticate(self, login, password):
        resp = self.call_api("/api/1.0/authentication.json", post={
            "userName": str(login),
            "password": str(password),
        })

        self.token = str(resp["token"])

    def get_task_list(self):
        resp = self.call_api("/api/1.0/project/task/@self.json")
        return resp

    def call_api(self, uri, post=None, get=None):
        uri = "http://" + self.hostname + uri

        if post is None:
            data = None
        else:
            data = urllib.urlencode(post)

        if get is not None:
            uri += "?" + urllib.urlencode(get)

        req = urllib2.Request(uri, data)
        if self.token is not None:
            req.add_header("Authorization", self.token)
        req.add_header("Accept", "application/json")

        res = urllib2.urlopen(req)
        if res.getcode() >= 400:
            raise Exception("Error accessing the API: %s" % res.read())

        response = res.read()

        return json.loads(response)["response"]


class TeamLabIssue(Issue):
    URL = 'teamlab_url'
    ID = 'teamlab_id'
    TITLE = 'teamlab_title'
    PROJECTOWNER_ID = 'teamlab_projectowner_id'

    UDAS = {
        URL: {
            'type': 'string',
            'label': 'Teamlab URL',
        },
        ID: {
            'type': 'string',
            'label': 'Teamlab ID',
        },
        TITLE: {
            'type': 'string',
            'label': 'Teamlab Title',
        },
        PROJECTOWNER_ID: {
            'type': 'string',
            'label': 'Teamlab ProjectOwner ID',
        }
    }
    UNIQUE_KEY = (URL, )

    def to_taskwarrior(self):
        return {
            'project': self.get_project(),
            'priority': self.get_priority(),

            self.TITLE: self.record['title'],
            self.ID: self.record['id'],
            self.URL: self.get_issue_url(),
            self.PROJECTOWNER_ID: self.record['projectOwner']['id'],
        }

    def get_default_description(self):
        return self.build_default_description(
            title=self.record['title'],
            url=self.get_issue_url(),
            number=self.record['id'],
            cls='issue',
        )

    def get_project(self):
        return self.origin['project_name']

    def get_issue_url(self):
        return "http://%s/products/projects/tasks.aspx?prjID=%d&id=%d" % (
            self.origin['hostname'],
            self.record["projectOwner"]["id"],
            self.record["id"]
        )

    def get_priority(self):
        if self.record["priority"] == 1:
            return "H"
        return "M"


class TeamLabService(IssueService):
    ISSUE_CLASS = TeamLabIssue

    def __init__(self, *args, **kw):
        super(TeamLabService, self).__init__(*args, **kw)

        self.hostname = self.config.get(self.target, 'hostname')
        _login = self.config.get(self.target, 'login')
        _password = self.config.get(self.target, 'password')
        if not _password or _password.startswith("@oracle:"):
            service = "teamlab://%s@%s" % (_login, self.hostname)
            _password = get_service_password(
                service, _login, oracle=_password,
                interactive=self.config.interactive
            )

        self.client = TeamLabClient(self.hostname)
        self.client.authenticate(_login, _password)

        self.project_name = self.hostname
        if self.config.has_option(self.target, "project_name"):
            self.project_name = self.config.get(self.target, "project_name")

    def get_service_metadata(self):
        return {
            'hostname': self.hostname,
            'project_name': self.project_name,
        }

    @classmethod
    def validate_config(cls, config, target):
        for k in ('login', 'password', 'hostname'):
            if not config.has_option(target, k):
                die("[%s] has no '%s'" % (target, k))

        IssueService.validate_config(config, target)

    def issues(self):
        issues = self.client.get_task_list()
        log.name(self.target).debug(
            " Remote has {0} total issues.", len(issues))

        # Filter out closed tasks.
        issues = filter(lambda i: i["status"] == 1, issues)
        log.name(self.target).debug(
            " Remote has {0} active issues.", len(issues))

        for issue in issues:
            yield self.get_issue_for_record(issue)
