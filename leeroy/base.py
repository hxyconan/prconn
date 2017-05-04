# Copyright 2012 litl, LLC.  Licensed under the MIT license.

import logging, time

from flask import Blueprint, current_app, json, request, Response, abort
from werkzeug.exceptions import BadRequest, NotFound

from . import github, jenkins

base = Blueprint("base", __name__)


@base.route("/ping")
def ping():
    return "pong"


def _parse_jenkins_json(request):
    # The Jenkins notification plugin (at least as of 1.4) incorrectly sets
    # its Content-type as application/x-www-form-urlencoded instead of
    # application/json.  As a result, all of the data gets stored as a key
    # in request.form.  Try to detect that and deal with it.
    if len(request.form) == 1:
        try:
            return json.loads(request.form.keys()[0])
        except ValueError:
            # Seems bad that there's only 1 key, but press on
            return request.form
    else:
        return request.json


@base.route("/notification/jenkins", methods=["POST"])
def jenkins_notification():
    data = _parse_jenkins_json(request)
    logging.debug("The data request to /notification/jenkins: %s", json.dumps(data))

    git_base_repo = data["build"]["parameters"]["GIT_BASE_REPO"]
    repo_config = github.get_repo_config(current_app, git_base_repo)
    if repo_config is None:
        err_msg = "No repo config for {0}".format(git_base_repo)
        logging.warn(err_msg)
        raise NotFound(err_msg)

    jenkins_name = data["name"]
    jenkins_number = data["build"]["number"]

    #The full_url parameter does not existed, so get jenkins_domain from settings.py to generate the jenkins full url for this job
    jenkins_domain = github.get_jenkins_domain(current_app, repo_config)
    jenkins_url_relative = data["build"]["url"]
    jenkins_url = jenkins_domain + jenkins_url_relative

    phase = data["build"]["phase"]

    logging.debug("Received Jenkins notification for %s %s (%s): %s",
                  jenkins_name, jenkins_number, jenkins_url, phase)

    if phase not in ("STARTED", "FINALIZED"):
        return Response(status=204)

    
    git_sha1 = data["build"]["parameters"]["GIT_SHA1"]

    # Generate the message for indicate the new pull request site url, showed in github pull request issue profile page when jenkins build successed
    targetsite = data["build"]["parameters"]["TARGETSITE"]
    pr_number = data["build"]["parameters"]["NUMBER"]
    domain_suffix = github.get_domain_suffix(current_app, repo_config)
    pr_site_url = "http://pr" + pr_number + "." + targetsite + domain_suffix
    logging.debug("The build pull request site url: %s", pr_site_url)


    desc_prefix = "Build #{0}".format(jenkins_number)

    if phase == "STARTED":
        github_state = "pending"
        github_desc = desc_prefix + " is running"
    else:
        status = data["build"]["status"]

        if status == "SUCCESS":
            github_state = "success"
            github_desc = desc_prefix + " succeeded. " + pr_site_url
        elif status == "FAILURE" or status == "UNSTABLE":
            github_state = "failure"
            github_desc = desc_prefix + " has failed"
        elif status == "ABORTED":
            github_state = "error"
            github_desc = desc_prefix + " has encountered an error"
        else:
            logging.debug("Did not understand '%s' build status. Aborting.",
                          status)
            abort()

    logging.debug(github_desc)

    logging.debug("current_app: '%s', repo_config: '%s', git_base_repo: '%s', git_sha1: '%s', github_state: '%s', github_desc: '%s', jenkins_url: '%s'",
                 current_app,
                 repo_config,
                 git_base_repo,
                 git_sha1,
                 github_state,
                 github_desc,
                 jenkins_url)

    github.update_status(current_app,
                         repo_config,
                         git_base_repo,
                         git_sha1,
                         github_state,
                         github_desc,
                         jenkins_url)

    return Response(status=204)


@base.route("/notification/github", methods=["POST"])
def github_notification():
    event_type = request.headers.get("X-GitHub-Event")
    if event_type is None:
        msg = "Got GitHub notification without a type"
        logging.warn(msg)
        return BadRequest(msg)
    elif event_type == "ping":
        return Response(status=200)
    elif event_type != "pull_request":
        msg = "Got unknown GitHub notification event type: %s" % (event_type,)
        logging.warn(msg)
        return BadRequest(msg)

    action = request.json["action"]
    pull_request = request.json["pull_request"]
    body = pull_request["body"]
    number = pull_request["number"]
    html_url = pull_request["html_url"]
    base_repo_name = github.get_repo_name(pull_request, "base")

    logging.debug("Received GitHub pull request notification for "
                  "%s %s (%s): %s",
                  base_repo_name, number, html_url, action)

    # Get targetsite name
    logging.debug("Pull request body message: "
                  "%s",
                  body)

    targetsite = ''
    body_lines = body.split('\r\n')
    for line in body_lines:
        if 'site:' in line:
            targetsite = line.split(':')[1].lower()
            break
    logging.debug("Targetsite: %s", targetsite)

    if targetsite == '':
        logging.debug("Targetsite value not given, Jenkins don not know which site to build.")
        return Response(status=204)

    if action not in ("opened", "reopened", "synchronize"):
        logging.debug("Ignored '%s' action." % action)
        return Response(status=204)

    repo_config = github.get_repo_config(current_app, base_repo_name)

    if repo_config is None:
        err_msg = "No repo config for {0}".format(base_repo_name)
        logging.warn(err_msg)
        raise NotFound(err_msg)

    # There is a race condition in the GitHub API in which requesting
    # the commits for a pull request can return a 404.  Try a few
    # times and back off if we get an error.
    tries_left = 5
    while True:
        tries_left -= 1
        try:
            head_repo_name, shas = github.get_commits(current_app,
                                                      repo_config,
                                                      pull_request)
            break
        except Exception, e:
            if tries_left == 0:
                raise

            logging.debug("Got exception fetching commits (tries left: %d): %s",
                          tries_left, e)
            time.sleep(5 - tries_left)

    logging.debug("Trigging builds for %d commits", len(shas))

    html_url = pull_request["html_url"]

    for sha in shas:
        github.update_status(current_app,
                             repo_config,
                             base_repo_name,
                             sha,
                             "pending",
                             "Jenkins build is being scheduled")

        logging.debug("Scheduling build the targetsite: %s with %s %s", targetsite, head_repo_name, sha)
        ok = jenkins.schedule_build(current_app,
                                    repo_config,
                                    targetsite,
                                    number,
                                    head_repo_name,
                                    sha,
                                    html_url)

        if ok:
            github_state = "pending"
            github_desc = "Jenkins build has been queued"
        else:
            github_state = "error"
            github_desc = "Scheduling Jenkins job failed"

        github.update_status(current_app,
                             repo_config,
                             base_repo_name,
                             sha,
                             github_state,
                             github_desc)

    return Response(status=204)
