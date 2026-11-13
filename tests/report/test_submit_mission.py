"""Unit and end-to-end tests for submit_mission.py (ActionBoard CLI mission submission)."""

import base64
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS_DIR = os.path.join(ROOT, "src", "skills", "mission-report", "scripts")
sys.path.insert(0, SCRIPTS_DIR)

import submit_mission  # noqa: E402


def make_jwt(claims):
    header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256", "typ": "JWT"}).encode("utf-8")).decode("ascii").rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode("utf-8")).decode("ascii").rstrip("=")
    return "%s.%s.signature" % (header, payload)


class FakeHTTPResponse:
    def __init__(self, body_bytes, status=200):
        self._buf = io.BytesIO(body_bytes)
        self.status = status

    def read(self):
        return self._buf.read()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class MockActionBoardTransport:
    """Intercepts AppSync GraphQL POSTs and S3 SigV4 PUTs without network calls."""

    def __init__(self, fail_submit_reports_folder=False):
        self.graphql_calls = []
        self.s3_puts = []
        self.fail_submit_reports_folder = fail_submit_reports_folder
        self.folder_files = []
        exp = int(time.time()) + 3600
        self.main_access_token = make_jwt({"sub": "user-main-1", "exp": exp})
        self.main_id_token = make_jwt({"sub": "user-main-1", "custom:profileId": "prof-agent-007", "exp": exp})
        self.pod_id_token = make_jwt({
            "sub": "user-pod-1",
            "custom:podId": "pod-alpha-1",
            "custom:profileId": "prof-agent-007",
            "exp": exp,
        })

    def __call__(self, req, timeout=30):
        url = req.full_url
        method = req.get_method()
        headers = {k.lower(): v for k, v in req.header_items()}

        if method == "PUT" and ".s3." in url:
            self.s3_puts.append({
                "url": url,
                "headers": headers,
                "body": req.data or b"",
            })
            return FakeHTTPResponse(b"")

        payload = json.loads((req.data or b"{}").decode("utf-8"))
        query = payload.get("query") or ""
        variables = payload.get("variables") or {}
        self.graphql_calls.append({
            "url": url,
            "headers": headers,
            "query": query,
            "variables": variables,
        })

        if "auth_login" in query:
            resp = {
                "data": {
                    "auth_login": {
                        "success": True,
                        "message": "Login ok",
                        "data": {
                            "tokens": {
                                "accessToken": self.main_access_token,
                                "idToken": self.main_id_token,
                                "refreshToken": "refresh-tok-123",
                                "expiresIn": 3600,
                                "tokenType": "Bearer",
                            },
                            "user": {
                                "profileId": "prof-agent-007",
                                "userId": "user-main-1",
                                "email": variables["input"]["email"],
                                "name": "Dev User",
                            },
                        },
                    }
                }
            }
        elif "auth_refreshToken" in query:
            resp = {
                "data": {
                    "auth_refreshToken": {
                        "success": True,
                        "message": "Token refreshed",
                        "data": {
                            "tokens": {
                                "accessToken": self.main_access_token,
                                "idToken": self.main_id_token,
                                "refreshToken": "refresh-tok-456",
                                "expiresIn": 3600,
                                "tokenType": "Bearer",
                            },
                        },
                    }
                }
            }
        elif "pods_getMyPods" in query:
            resp = {
                "data": {
                    "pods_getMyPods": {
                        "success": True,
                        "message": "ok",
                        "data": [
                            {
                                "podId": "pod-alpha-1",
                                "podName": "Alpha Engineering Pod",
                                "slug": "alpha-pod",
                                "hostname": "alpha.actionboard.ai",
                                "bucketName": "actionboard-kb-agent",
                                "status": "ACTIVE",
                                "memberRole": "ADMIN",
                                "memberStatus": "ACTIVE",
                            }
                        ],
                    }
                }
            }
        elif "pods_createExchangeCode" in query:
            resp = {
                "data": {
                    "pods_createExchangeCode": {
                        "success": True,
                        "message": "ok",
                        "data": {"code": "exch-code-999"},
                    }
                }
            }
        elif "pods_consumeExchangeCode" in query:
            resp = {
                "data": {
                    "pods_consumeExchangeCode": {
                        "success": True,
                        "message": "ok",
                        "data": {
                            "token": self.pod_id_token,
                            "idToken": self.pod_id_token,
                            "accessToken": "pod-access-tok",
                            "refreshToken": "pod-refresh-tok",
                            "expiresIn": 3600,
                            "userId": "user-pod-1",
                            "email": "dev@actionboard.ai",
                            "username": "dev@actionboard.ai",
                        },
                    }
                }
            }
        elif "boards_getMyBoards" in query:
            resp = {
                "data": {
                    "boards_getMyBoards": {
                        "success": True,
                        "message": "ok",
                        "data": [
                            {
                                "boardId": "board-eng-42",
                                "name": "Investor & Engineering Board",
                                "description": "Main board",
                                "ownerId": "user-pod-1",
                                "podId": "pod-alpha-1",
                                "memberCount": 5,
                                "boardStatus": "ACTIVE",
                                "boardType": "PREMIUM",
                                "createdAt": "2026-11-01T00:00:00Z",
                                "updatedAt": "2026-11-01T00:00:00Z",
                            }
                        ],
                    }
                }
            }
        elif "assistprofile_listMissionsByBoard" in query:
            resp = {
                "data": {
                    "assistprofile_listMissionsByBoard": {
                        "nextToken": None,
                        "items": [],
                    }
                }
            }
        elif "assistprofile_listMissionsByAgent" in query:
            resp = {
                "data": {
                    "assistprofile_listMissionsByAgent": {
                        "nextToken": None,
                        "items": [
                            {
                                "boardId": "board-eng-42",
                                "missionId": "mission-assigned-555",
                                "ownerProfileId": "prof-boss-001",
                                "assignedAgentProfileId": "prof-agent-007",
                                "title": "Implement Zero-Trust Webhook Verifier",
                                "shortDescription": "Build and verify HMAC-SHA256 webhook signature verification for ActionBoard.",
                                "startDate": "2026-11-13T08:00:00Z",
                                "endDate": "2026-11-20T18:00:00Z",
                                "status": "INITIATED",
                                "missionFolderId": "folder-assigned-root",
                                "reportsSubfolderId": "folder-assigned-rep",
                                "totalFiles": 0,
                                "createdAt": "2026-11-13T08:00:00Z",
                                "updatedAt": "2026-11-13T08:00:00Z",
                            }
                        ],
                    }
                }
            }
        elif "assistprofile_getMyMissionInvitations" in query:
            resp = {
                "data": {
                    "assistprofile_getMyMissionInvitations": {
                        "nextToken": None,
                        "items": [
                            {
                                "invitationId": "inv-boss-888",
                                "missionId": "mission-assigned-555",
                                "boardId": "board-eng-42",
                                "invitedProfileId": "prof-agent-007",
                                "invitedBy": "prof-boss-001",
                                "status": "PENDING",
                                "message": "Please lead the webhook verifier task",
                                "expiresAt": "2026-11-25T00:00:00Z",
                                "createdAt": "2026-11-13T08:05:00Z",
                                "updatedAt": "2026-11-13T08:05:00Z",
                            }
                        ],
                    }
                }
            }
        elif "assistprofile_acceptMissionInvitation" in query:
            resp = {
                "data": {
                    "assistprofile_acceptMissionInvitation": {
                        "invitationId": variables["invitationId"],
                        "missionId": "mission-assigned-555",
                        "boardId": variables["boardId"],
                        "invitedProfileId": "prof-agent-007",
                        "invitedBy": "prof-boss-001",
                        "status": "ACCEPTED",
                        "acceptedAt": "2026-11-13T09:00:00Z",
                        "updatedAt": "2026-11-13T09:00:00Z",
                    }
                }
            }
        elif "assistprofile_getMission(" in query:
            resp = {
                "data": {
                    "assistprofile_getMission": {
                        "boardId": variables["boardId"],
                        "missionId": variables["missionId"],
                        "ownerProfileId": "prof-boss-001",
                        "assignedAgentProfileId": "prof-agent-007",
                        "title": "Implement Zero-Trust Webhook Verifier",
                        "shortDescription": "Build and verify HMAC-SHA256 webhook signature verification for ActionBoard.",
                        "startDate": "2026-11-13T08:00:00Z",
                        "endDate": "2026-11-20T18:00:00Z",
                        "status": "INITIATED",
                        "missionFolderId": "folder-assigned-root",
                        "reportsSubfolderId": "folder-assigned-rep",
                        "totalFiles": 0,
                        "createdAt": "2026-11-13T08:00:00Z",
                        "updatedAt": "2026-11-13T08:00:00Z",
                    }
                }
            }
        elif "assistprofile_listMissionPlansByMission" in query:
            resp = {
                "data": {
                    "assistprofile_listMissionPlansByMission": {
                        "nextToken": None,
                        "items": [
                            {
                                "missionId": variables["missionId"],
                                "planId": "plan-assigned-777",
                                "boardId": "board-eng-42",
                                "ownerProfileId": "prof-boss-001",
                                "createdByProfileId": "prof-boss-001",
                                "assignedAgentProfileId": "prof-agent-007",
                                "plan": (
                                    "# Mission Brief — Implement Zero-Trust Webhook Verifier\n\n"
                                    "## Objective\nVerify incoming webhook signatures using HMAC-SHA256.\n\n"
                                    "---\n\n"
                                    "# Mission Plan — Implement Zero-Trust Webhook Verifier\n\n"
                                    "## Agent Assignments\n"
                                    "| Agent | Task | Files Owned |\n"
                                    "|---|---|---|\n"
                                    "| Red | Implement HMAC verifier | `src/webhook.py` |\n"
                                    "| Yellow | Add unit tests | `tests/test_webhook.py` |\n"
                                ),
                                "status": "APPROVED",
                                "createdAt": "2026-11-13T08:10:00Z",
                                "updatedAt": "2026-11-13T08:10:00Z",
                            }
                        ],
                    }
                }
            }
        elif "filemanager_filesByBoardAndFolder" in query:
            resp = {
                "data": {
                    "filemanager_filesByBoardAndFolder": {
                        "success": True,
                        "message": "ok",
                        "data": {"nextToken": None, "items": self.folder_files},
                    }
                }
            }
        elif "assistprofile_createMission(" in query:
            inp = variables["input"]
            resp = {
                "data": {
                    "assistprofile_createMission": {
                        "boardId": inp["boardId"],
                        "missionId": "mission-uuid-1001",
                        "ownerProfileId": "prof-agent-007",
                        "assignedAgentProfileId": inp.get("assignedAgentProfileId"),
                        "title": inp["title"],
                        "shortDescription": inp["shortDescription"],
                        "status": "INITIATED",
                        "missionFolderId": "folder-root-1",
                        "reportsSubfolderId": "folder-rep-1",
                        "totalFiles": 0,
                        "createdAt": "2026-11-13T10:00:00Z",
                        "updatedAt": "2026-11-13T10:00:00Z",
                    }
                }
            }
        elif "assistprofile_createMissionPlan" in query:
            inp = variables["input"]
            resp = {
                "data": {
                    "assistprofile_createMissionPlan": {
                        "missionId": inp["missionId"],
                        "planId": "plan-uuid-2002",
                        "boardId": inp["boardId"],
                        "ownerProfileId": "prof-agent-007",
                        "createdByProfileId": "prof-agent-007",
                        "assignedAgentProfileId": inp.get("assignedAgentProfileId"),
                        "lastEditedByProfileId": "prof-agent-007",
                        "plan": inp["plan"],
                        "status": "DRAFT",
                        "createdAt": "2026-11-13T10:01:00Z",
                        "updatedAt": "2026-11-13T10:01:00Z",
                    }
                }
            }
        elif "assistprofile_updateMissionPlan" in query:
            inp = variables["input"]
            resp = {
                "data": {
                    "assistprofile_updateMissionPlan": {
                        "missionId": inp["missionId"],
                        "planId": inp["planId"],
                        "boardId": inp["boardId"],
                        "plan": inp.get("plan"),
                        "status": inp.get("status") or "DRAFT",
                        "updatedAt": "2026-11-13T10:02:00Z",
                    }
                }
            }
        elif "assistprofile_submitMissionPlan" in query:
            inp = variables["input"]
            resp = {
                "data": {
                    "assistprofile_submitMissionPlan": {
                        "missionId": inp["missionId"],
                        "planId": "plan-inv-3003",
                        "boardId": inp["boardId"],
                        "invitationId": inp["invitationId"],
                        "plan": inp["plan"],
                        "status": "SUBMITTED",
                        "reviewStatus": "PENDING_REVIEW",
                        "createdAt": "2026-11-13T10:02:00Z",
                        "updatedAt": "2026-11-13T10:02:00Z",
                    }
                }
            }
        elif "assistprofile_getMissionInvitation" in query:
            resp = {
                "data": {
                    "assistprofile_getMissionInvitation": {
                        "invitationId": variables["invitationId"],
                        "missionId": "mission-invited-77",
                        "boardId": variables["boardId"],
                        "invitedProfileId": "prof-agent-007",
                        "status": "ACCEPTED",
                    }
                }
            }
        elif "assistprofile_submitReports" in query:
            if self.fail_submit_reports_folder:
                resp = {
                    "errors": [
                        {"message": "Mission folder not found. Only missions created after this feature is enabled have folders."}
                    ]
                }
            else:
                inp = variables["input"]
                files_out = []
                for idx, r in enumerate(inp["reports"], 1):
                    files_out.append({
                        "id": "file-%d" % idx,
                        "boardId": inp["boardId"],
                        "folderId": "folder-rep-1",
                        "fileName": r["fileName"],
                        "fileType": r["fileType"],
                        "fileSize": r["fileSize"],
                        "url": r["url"],
                        "note": r.get("note"),
                        "tags": r.get("tags"),
                        "createdAt": "2026-11-13T10:03:00Z",
                        "updatedAt": "2026-11-13T10:03:00Z",
                    })
                resp = {
                    "data": {
                        "assistprofile_submitReports": {
                            "success": True,
                            "message": "Successfully uploaded %d report file(s)" % len(files_out),
                            "totalFiles": len(files_out),
                            "files": files_out,
                        }
                    }
                }
        elif "filemanager_foldersByBoardIdIndex" in query:
            resp = {"data": {"filemanager_foldersByBoardIdIndex": {"success": True, "data": {"items": []}}}}
        elif "filemanager_createFolder" in query:
            fname = variables["input"]["folderName"]
            fid = "folder-legacy-reports" if fname == "Reports" else "folder-legacy-root"
            resp = {
                "data": {
                    "filemanager_createFolder": {
                        "success": True,
                        "data": {
                            "id": fid,
                            "boardId": variables["input"]["boardId"],
                            "folderName": fname,
                            "parentFolderId": variables["input"].get("parentFolderId"),
                        },
                    }
                }
            }
        elif "filemanager_createFile" in query:
            inp = variables["input"]
            resp = {
                "data": {
                    "filemanager_createFile": {
                        "success": True,
                        "data": {
                            "id": "legacy-file-" + inp["fileName"],
                            "boardId": inp["boardId"],
                            "folderId": inp["folderId"],
                            "fileName": inp["fileName"],
                            "fileType": inp["fileType"],
                            "fileSize": inp["fileSize"],
                            "url": inp["url"],
                        },
                    }
                }
            }
        elif "assistprofile_updateMissionStatus" in query:
            inp = variables["input"]
            resp = {
                "data": {
                    "assistprofile_updateMissionStatus": {
                        "boardId": inp["boardId"],
                        "missionId": inp["missionId"],
                        "status": inp["status"],
                        "updatedAt": "2026-11-13T10:04:00Z",
                    }
                }
            }
        else:
            raise AssertionError("Unexpected GraphQL query: %s" % query)

        return FakeHTTPResponse(json.dumps(resp).encode("utf-8"))


class TestSubmitMissionCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ab-submit-test-")
        self.cred_file = os.path.join(self.tmp, "credentials.json")
        self.cfg_file = os.path.join(self.tmp, "config.json")
        self.mission_dir = os.path.join(self.tmp, "docs", "missions", "2026-11-13-cli-mission-upload")
        os.makedirs(self.mission_dir)

        with open(os.path.join(self.mission_dir, "mission-brief.md"), "w", encoding="utf-8") as fh:
            fh.write("# Mission Brief: CLI Mission Upload\n\n## Objective\nSubmit mission docs from CLI.\n")
        with open(os.path.join(self.mission_dir, "mission-plan.md"), "w", encoding="utf-8") as fh:
            fh.write("# Mission Plan — CLI Mission Upload\n\n## Wave 1\nBuild submit_mission.py.\n")
        with open(os.path.join(self.mission_dir, "mission-report.md"), "w", encoding="utf-8") as fh:
            fh.write("# Mission Report — CLI Mission Upload\n\nAll assignments completed.\n")
        with open(os.path.join(self.mission_dir, "mission-report.html"), "w", encoding="utf-8") as fh:
            fh.write("<!doctype html><html><body>Dashboard</body></html>\n")
        with open(os.path.join(self.mission_dir, "mission-report.jsonld"), "w", encoding="utf-8") as fh:
            json.dump({
                "@context": "https://schema.org",
                "@graph": [
                    {
                        "@id": "urn:voltron:mission:cli-mission-upload",
                        "@type": "Project",
                        "name": "CLI Mission Upload",
                        "description": "Submit mission docs from CLI to ActionBoard Pod and Board.",
                        "startDate": "2026-11-13T09:00:00Z",
                        "endDate": "2026-11-13T10:00:00Z",
                    }
                ],
            }, fh)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_configure_from_env_file_sets_0600_permissions(self):
        env_md = os.path.join(self.tmp, "mission-plan-api.md")
        with open(env_md, "w", encoding="utf-8") as fh:
            fh.write(
                "# Config\n"
                "APPSYNC_GRAPHQL_ENDPOINT=https://example.appsync-api.ap-southeast-1.amazonaws.com/graphql\n"
                "APPSYNC_API_KEY=da2-testapikey123\n"
                "COGNITO_DOMAIN=https://absaas-dev.auth.ap-southeast-1.amazoncognito.com/\n"
                "COGNITO_CLIENT_ID=client123\n"
                "S3_REGION=ap-southeast-1\n"
                "S3_BUCKET_NAME=actionboard-kb-agent\n"
                "S3_PREFIX=PremiumBoardKB/Boards/Investor+Boards\n"
            )
        rc = submit_mission.main([
            "--credentials-file", self.cred_file,
            "--config", self.cfg_file,
            "configure",
            "--from-env-file", env_md,
            "--aws-access-key-id", "AKIATESTKEY",
            "--aws-secret-access-key", "SECRETTESTKEY",
        ])
        self.assertEqual(rc, 0)
        if os.name != "nt":
            # Windows has no POSIX modes (stat always reports 0o666); the user profile ACL protects the file there.
            mode = stat.S_IMODE(os.stat(self.cred_file).st_mode)
            self.assertEqual(mode, 0o600)
        saved = submit_mission.load_json_file(self.cred_file)
        self.assertEqual(saved["appsync_endpoint"], "https://example.appsync-api.ap-southeast-1.amazonaws.com/graphql")
        self.assertEqual(saved["appsync_api_key"], "da2-testapikey123")
        self.assertEqual(saved["s3_bucket"], "actionboard-kb-agent")
        self.assertEqual(saved["s3_prefix"], "PremiumBoardKB/Boards/Investor+Boards")
        self.assertEqual(saved["aws_access_key_id"], "AKIATESTKEY")

    def test_parse_metadata_and_collect_files(self):
        meta = submit_mission.parse_mission_metadata(self.mission_dir)
        self.assertEqual(meta["slug"], "cli-mission-upload")
        self.assertEqual(meta["title"], "CLI Mission Upload")
        self.assertIn("Submit mission docs from CLI", meta["short_description"])
        self.assertEqual(meta["start_date"], "2026-11-13T09:00:00Z")
        self.assertEqual(meta["end_date"], "2026-11-13T10:00:00Z")

        plan_md = submit_mission.build_plan_markdown(self.mission_dir)
        self.assertIn("# Mission Brief: CLI Mission Upload", plan_md)
        self.assertIn("# Mission Plan — CLI Mission Upload", plan_md)

        files = submit_mission.collect_mission_files(self.mission_dir)
        names = [f["fileName"] for f in files]
        self.assertEqual(names, [
            "mission-report.md",
            "mission-report.html",
            "mission-report.jsonld",
            "mission-brief.md",
            "mission-plan.md",
        ])

    def test_list_missions_omits_unused_null_next_token_argument(self):
        def reject_null_next_token(req, timeout=30):
            payload = json.loads((req.data or b"{}").decode("utf-8"))
            query = payload.get("query") or ""
            if "nextToken: $nextToken" in query:
                body = {
                    "errors": [{
                        "message": "Invalid input: expected string, received null",
                        "path": ["nextToken"],
                    }]
                }
            else:
                body = {
                    "data": {
                        "assistprofile_listMissionsByBoard": {
                            "nextToken": None,
                            "items": [],
                        }
                    }
                }
            return FakeHTTPResponse(json.dumps(body).encode("utf-8"))

        missions = submit_mission.fetch_missions_by_board(
            {
                "endpoint": "https://example.appsync-api.ap-southeast-1.amazonaws.com/graphql",
                "api_key": "test-api-key",
            },
            "pod-id-token",
            "board-123",
            opener=reject_null_next_token,
        )

        self.assertEqual(missions, [])

    def test_end_to_end_login_select_and_submit_with_s3_sigv4(self):
        transport = MockActionBoardTransport()
        submit_mission.main([
            "--credentials-file", self.cred_file,
            "--config", self.cfg_file,
            "configure",
            "--endpoint", "https://example.appsync-api.ap-southeast-1.amazonaws.com/graphql",
            "--api-key", "da2-testapikey123",
            "--aws-access-key-id", "AKIATESTKEY",
            "--aws-secret-access-key", "SECRETTESTKEY",
        ])

        rc_login = submit_mission.main([
            "--credentials-file", self.cred_file,
            "--config", self.cfg_file,
            "login",
            "--email", "dev@actionboard.ai",
            "--password", "S3cretP@ss!",
        ], opener=transport)
        self.assertEqual(rc_login, 0)

        rc_select = submit_mission.main([
            "--credentials-file", self.cred_file,
            "--config", self.cfg_file,
            "select",
            "--pod", "alpha-pod",
            "--board", "board-eng-42",
        ], opener=transport)
        self.assertEqual(rc_select, 0)

        cfg = submit_mission.load_json_file(self.cfg_file)
        self.assertEqual(cfg["pod_id"], "pod-alpha-1")
        self.assertEqual(cfg["board_id"], "board-eng-42")

        rc_submit = submit_mission.main([
            "--credentials-file", self.cred_file,
            "--config", self.cfg_file,
            "submit",
            "--mission-dir", self.mission_dir,
            "--no-input",
            "--json",
        ], opener=transport)
        self.assertEqual(rc_submit, 0)

        # Verify S3 SigV4 uploads happened for all 5 mission files
        self.assertEqual(len(transport.s3_puts), 5)
        first_put = transport.s3_puts[0]
        self.assertIn(
            "https://actionboard-kb-agent.s3.ap-southeast-1.amazonaws.com/"
            "PremiumBoardKB/Boards/Investor%2BBoards/board-eng-42/missions/mission-uuid-1001/",
            first_put["url"],
        )
        self.assertTrue(first_put["headers"]["authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIATESTKEY/"))
        self.assertIn("x-amz-content-sha256", first_put["headers"])
        self.assertEqual(first_put["headers"]["x-amz-meta-missionid"], "mission-uuid-1001")

        # Verify AppSync mutations called in order: createMission, createMissionPlan, submitReports, updateMissionStatus
        queries = [c["query"] for c in transport.graphql_calls]
        self.assertTrue(any("assistprofile_createMission(" in q for q in queries))
        self.assertTrue(any("assistprofile_createMissionPlan(" in q for q in queries))
        self.assertTrue(any("assistprofile_submitReports(" in q for q in queries))
        self.assertTrue(any("assistprofile_updateMissionStatus(" in q for q in queries))

        # Verify mission_id and plan_id were persisted in .actionboard/config.json for idempotent re-runs
        cfg_after = submit_mission.load_json_file(self.cfg_file)
        saved_mission = cfg_after["missions"]["cli-mission-upload"]
        self.assertEqual(saved_mission["mission_id"], "mission-uuid-1001")
        self.assertEqual(saved_mission["plan_id"], "plan-uuid-2002")

        # Re-running submit updates the existing planId instead of creating a duplicate mission
        rc_resubmit = submit_mission.main([
            "--credentials-file", self.cred_file,
            "--config", self.cfg_file,
            "submit",
            "--mission-dir", self.mission_dir,
            "--skip-s3",
            "--no-input",
        ], opener=transport)
        self.assertEqual(rc_resubmit, 0)
        self.assertTrue(any("assistprofile_updateMissionPlan(" in c["query"] for c in transport.graphql_calls))

    def test_legacy_mission_fallback_to_filemanager(self):
        transport = MockActionBoardTransport(fail_submit_reports_folder=True)
        submit_mission.main([
            "--credentials-file", self.cred_file,
            "--config", self.cfg_file,
            "configure",
            "--endpoint", "https://example.appsync-api.ap-southeast-1.amazonaws.com/graphql",
            "--api-key", "da2-testapikey123",
        ])
        submit_mission.main([
            "--credentials-file", self.cred_file,
            "--config", self.cfg_file,
            "login",
            "--email", "dev@actionboard.ai",
            "--password", "S3cretP@ss!",
        ], opener=transport)

        rc = submit_mission.main([
            "--credentials-file", self.cred_file,
            "--config", self.cfg_file,
            "submit",
            "--mission-dir", self.mission_dir,
            "--pod", "pod-alpha-1",
            "--board", "board-eng-42",
            "--skip-s3",
            "--no-input",
        ], opener=transport)
        self.assertEqual(rc, 0)
        queries = [c["query"] for c in transport.graphql_calls]
        self.assertTrue(any("filemanager_createFolder" in q for q in queries))
        create_file_calls = [c for c in transport.graphql_calls if "filemanager_createFile" in c["query"]]
        self.assertEqual(len(create_file_calls), 5)

    def test_invitation_plan_submission(self):
        transport = MockActionBoardTransport()
        submit_mission.main([
            "--credentials-file", self.cred_file,
            "--config", self.cfg_file,
            "configure",
            "--endpoint", "https://example.appsync-api.ap-southeast-1.amazonaws.com/graphql",
            "--api-key", "da2-testapikey123",
        ])
        submit_mission.main([
            "--credentials-file", self.cred_file,
            "--config", self.cfg_file,
            "login",
            "--email", "dev@actionboard.ai",
            "--password", "S3cretP@ss!",
        ], opener=transport)

        rc = submit_mission.main([
            "--credentials-file", self.cred_file,
            "--config", self.cfg_file,
            "submit",
            "--mission-dir", self.mission_dir,
            "--pod", "pod-alpha-1",
            "--board", "board-eng-42",
            "--invitation-id", "inv-900",
            "--skip-s3",
            "--no-input",
        ], opener=transport)
        self.assertEqual(rc, 0)
        self.assertTrue(any("assistprofile_submitMissionPlan" in c["query"] for c in transport.graphql_calls))

    def test_assigned_and_fetch_workflow_roundtrip(self):
        transport = MockActionBoardTransport()
        submit_mission.main([
            "--credentials-file", self.cred_file,
            "--config", self.cfg_file,
            "configure",
            "--endpoint", "https://example.appsync-api.ap-southeast-1.amazonaws.com/graphql",
            "--api-key", "da2-testapikey123",
        ])
        submit_mission.main([
            "--credentials-file", self.cred_file,
            "--config", self.cfg_file,
            "login",
            "--email", "dev@actionboard.ai",
            "--password", "S3cretP@ss!",
        ], opener=transport)

        rc_assigned = submit_mission.main([
            "--credentials-file", self.cred_file,
            "--config", self.cfg_file,
            "assigned",
            "--no-input",
        ], opener=transport)
        self.assertEqual(rc_assigned, 0)

        fetched_dir = os.path.join(self.tmp, "docs", "missions", "2026-11-13-implement-zero-trust-webhook-verifier")
        rc_fetch = submit_mission.main([
            "--credentials-file", self.cred_file,
            "--config", self.cfg_file,
            "fetch",
            "--invitation-id", "inv-boss-888",
            "--out-dir", fetched_dir,
            "--accept",
            "--start",
            "--no-input",
        ], opener=transport)
        self.assertEqual(rc_fetch, 0)

        self.assertTrue(os.path.isfile(os.path.join(fetched_dir, "mission-brief.md")))
        self.assertTrue(os.path.isfile(os.path.join(fetched_dir, "mission-brief.jsonld")))
        self.assertTrue(os.path.isfile(os.path.join(fetched_dir, "mission-plan.md")))

        with open(os.path.join(fetched_dir, "mission-brief.md"), encoding="utf-8") as fh:
            brief_content = fh.read()
        with open(os.path.join(fetched_dir, "mission-plan.md"), encoding="utf-8") as fh:
            plan_content = fh.read()

        self.assertIn("Verify incoming webhook signatures using HMAC-SHA256", brief_content)
        self.assertIn("Implement HMAC verifier", plan_content)

        # Verify config.json recorded the assigned mission_id and plan_id
        cfg = submit_mission.load_json_file(self.cfg_file)
        linked = cfg["missions"]["implement-zero-trust-webhook-verifier"]
        self.assertEqual(linked["mission_id"], "mission-assigned-555")
        self.assertEqual(linked["plan_id"], "plan-assigned-777")
        self.assertEqual(linked["invitation_id"], "inv-boss-888")

        queries = [c["query"] for c in transport.graphql_calls]
        self.assertTrue(any("assistprofile_acceptMissionInvitation" in q for q in queries))
        self.assertTrue(any("assistprofile_updateMissionStatus" in q for q in queries))

    def test_skill_documented_flags_match_cli_parser(self):
        script_path = os.path.join(SCRIPTS_DIR, "submit_mission.py")
        for skill_dir in ("submit-mission", "fetch-mission"):
            skill_path = os.path.join(ROOT, "src", "skills", skill_dir, "SKILL.md")
            with open(skill_path, encoding="utf-8") as fh:
                skill_text = fh.read()

            for sub in ("status", "configure", "login", "pods", "boards", "assigned", "fetch", "select", "submit"):
                proc = subprocess.run(
                    [sys.executable, script_path, sub, "--help"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                    timeout=30,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)
                for match in re.finditer(r"submit_mission\.py %s((?:[^\n]*\\\n)*[^\n]*)" % sub, skill_text):
                    flags = set(re.findall(r"--[a-z0-9][a-z0-9-]*", match.group(1)))
                    for flag in flags:
                        self.assertIn(flag, proc.stdout, "%s: %s %s not in --help" % (skill_dir, sub, flag))

    def test_refresh_token_and_cached_pod_token_when_main_token_expired(self):
        transport = MockActionBoardTransport()
        expired_main = make_jwt({"sub": "user-main-1", "exp": int(time.time()) - 3600})
        valid_pod = transport.pod_id_token
        submit_mission.save_secure_json(self.cred_file, {
            "appsync_endpoint": "https://example.appsync-api.ap-southeast-1.amazonaws.com/graphql",
            "appsync_api_key": "da2-testapikey123",
            "email": "dev@actionboard.ai",
            "user_id": "user-main-1",
            "profile_id": "prof-agent-007",
            "access_token": expired_main,
            "refresh_token": "refresh-tok-123",
            "pod_tokens": {
                "pod-alpha-1": {
                    "id_token": valid_pod,
                    "expires_at": int(time.time()) + 86400,
                }
            },
        })
        submit_mission.save_config_json(self.cfg_file, {
            "pod_id": "pod-alpha-1",
            "pod_name": "Alpha Engineering Pod",
            "board_id": "board-eng-42",
            "board_name": "Investor & Engineering Board",
        })

        # 1. Submit succeeds using the valid 24h cached pod token without needing pods_getMyPods
        rc_submit = submit_mission.main([
            "--credentials-file", self.cred_file,
            "--config", self.cfg_file,
            "submit",
            "--mission-dir", self.mission_dir,
            "--skip-s3",
            "--no-input",
        ], opener=transport)
        self.assertEqual(rc_submit, 0)
        queries_so_far = [c["query"] for c in transport.graphql_calls]
        self.assertFalse(any("pods_getMyPods" in q for q in queries_so_far))

        # 2. Listing pods refreshes the expired main access_token via auth_refreshToken
        rc_pods = submit_mission.main([
            "--credentials-file", self.cred_file,
            "--config", self.cfg_file,
            "pods",
            "--no-input",
        ], opener=transport)
        self.assertEqual(rc_pods, 0)
        all_queries = [c["query"] for c in transport.graphql_calls]
        self.assertTrue(any("auth_refreshToken" in q for q in all_queries))

    def test_submit_without_aws_keys_uploads_through_pod_route(self):
        transport = MockActionBoardTransport()
        pod_uploads = []

        def opener(req, timeout=30):
            if "/api/s3/knowledge-base/upload" in req.full_url:
                pod_uploads.append(req)
                body = {"bucket": "pod-bucket", "key": "board-eng-42/missions/1-file", "region": "ap-southeast-1"}
                return FakeHTTPResponse(json.dumps(body).encode("utf-8"))
            return transport(req, timeout=timeout)

        base = ["--credentials-file", self.cred_file, "--config", self.cfg_file]
        submit_mission.main(base + [
            "configure", "--endpoint", "https://example.appsync-api.ap-southeast-1.amazonaws.com/graphql",
            "--api-key", "da2-testapikey123",
        ])
        submit_mission.main(base + ["login", "--email", "dev@actionboard.ai", "--password", "pw"], opener=opener)
        submit_mission.main(base + ["select", "--pod", "alpha-pod", "--board", "board-eng-42"], opener=opener)

        saved_env = dict(os.environ)
        for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
            os.environ.pop(key, None)
        os.environ["AWS_SHARED_CREDENTIALS_FILE"] = os.path.join(self.tmp, "no-aws-credentials")
        try:
            rc = submit_mission.main(base + ["submit", "--mission-dir", self.mission_dir, "--no-input"], opener=opener)
        finally:
            os.environ.clear()
            os.environ.update(saved_env)

        self.assertEqual(rc, 0)
        self.assertEqual(len(transport.s3_puts), 0)
        self.assertEqual(len(pod_uploads), 5)
        first = pod_uploads[0]
        self.assertEqual(first.full_url, "https://alpha.actionboard.ai/api/s3/knowledge-base/upload")
        self.assertEqual(first.get_header("Cookie"), "podId=pod-alpha-1")
        self.assertIn(b'name="boardId"\r\n\r\nboard-eng-42', first.data)
        self.assertIn(b"All assignments completed.", first.data)
        reports_call = [c for c in transport.graphql_calls if "assistprofile_submitReports(" in c["query"]][0]
        s3_object = reports_call["variables"]["input"]["reports"][0]["s3Object"]
        self.assertEqual(s3_object["bucket"], "pod-bucket")
        self.assertEqual(s3_object["key"], "board-eng-42/missions/1-file")

    def test_date_only_values_become_aws_datetime(self):
        self.assertEqual(submit_mission.to_aws_datetime("2026-11-13"), "2026-11-13T00:00:00Z")
        self.assertEqual(submit_mission.to_aws_datetime("2026-11-13T09:00:00Z"), "2026-11-13T09:00:00Z")
        self.assertIsNone(submit_mission.to_aws_datetime(None))

    def test_graphql_error_exits_cleanly_without_traceback(self):
        def opener(req, timeout=30):
            return FakeHTTPResponse(json.dumps({"errors": [{"message": "Variable 'x' has an invalid value."}]}).encode("utf-8"))

        with open(self.cred_file, "w", encoding="utf-8") as fh:
            json.dump({
                "appsync_endpoint": "https://example.appsync-api.ap-southeast-1.amazonaws.com/graphql",
                "appsync_api_key": "da2-testapikey123",
                "access_token": make_jwt({"sub": "u", "exp": int(time.time()) + 3600}),
            }, fh)
        with self.assertRaises(SystemExit) as ctx:
            submit_mission.main(["--credentials-file", self.cred_file, "--config", self.cfg_file, "pods", "--no-input"], opener=opener)
        self.assertEqual(ctx.exception.code, 2)

    def test_edge_proxy_mode_needs_no_api_key(self):
        transport = MockActionBoardTransport()
        signs = []
        downloads = []

        def opener(req, timeout=30):
            url = req.full_url
            if url.endswith("/s3/sign"):
                body = json.loads(req.data.decode("utf-8"))
                signs.append({"body": body, "edge": req.get_header("X-edge-auth")})
                signed = "https://%s.s3.ap-southeast-1.amazonaws.com/%s?X-Amz-Signature=x" % (body["bucket"], body["key"])
                return FakeHTTPResponse(json.dumps({"url": signed, "region": "ap-southeast-1"}).encode("utf-8"))
            if req.get_method() == "GET" and ".s3." in url:
                downloads.append(url)
                return FakeHTTPResponse(b"# Mission Brief from S3\n")
            return transport(req, timeout=timeout)

        base = ["--credentials-file", self.cred_file, "--config", self.cfg_file]
        saved_env = dict(os.environ)
        for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "APPSYNC_API_KEY",
                    "APPSYNC_GRAPHQL_ENDPOINT", "APPSYNC_URL", "ACTIONBOARD_EDGE_PROXY_URL"):
            os.environ.pop(key, None)
        os.environ["AWS_SHARED_CREDENTIALS_FILE"] = os.path.join(self.tmp, "no-aws-credentials")
        try:
            # No configure step at all: a fresh user only logs in.
            self.assertEqual(submit_mission.main(base + ["login", "--email", "dev@actionboard.ai", "--password", "pw"], opener=opener), 0)
            submit_mission.main(base + ["select", "--pod", "alpha-pod", "--board", "board-eng-42"], opener=opener)
            rc = submit_mission.main(base + ["submit", "--mission-dir", self.mission_dir, "--no-input"], opener=opener)
            self.assertEqual(rc, 0)

            transport.folder_files.append({
                "fileName": "mission-brief.md",
                "s3Object": {"bucket": "actionboard-kb-agent", "key": "PremiumBoardKB/Boards/b/missions/m/1-mission-brief.md"},
            })
            out_dir = os.path.join(self.tmp, "fetched")
            rc_fetch = submit_mission.main(base + ["fetch", "--invitation-id", "inv-boss-888", "--out-dir", out_dir, "--no-input"], opener=opener)
            self.assertEqual(rc_fetch, 0)
        finally:
            os.environ.clear()
            os.environ.update(saved_env)

        edge_graphql = submit_mission.DEFAULT_EDGE_PROXY_URL + "/graphql"
        self.assertTrue(transport.graphql_calls)
        for call in transport.graphql_calls:
            self.assertEqual(call["url"], edge_graphql)
            self.assertNotIn("x-api-key", call["headers"])
        pod_calls = [c for c in transport.graphql_calls if c["headers"].get("authorization") == "Bearer " + transport.pod_id_token]
        self.assertTrue(pod_calls)
        for call in pod_calls:
            self.assertEqual(call["headers"]["x-edge-auth"], "Bearer " + transport.main_access_token)

        puts = [s for s in signs if s["body"]["method"] == "PUT"]
        self.assertEqual(len(puts), 5)
        self.assertEqual(len(transport.s3_puts), 5)
        self.assertEqual(puts[0]["body"]["bucket"], "actionboard-kb-agent")
        self.assertTrue(puts[0]["body"]["key"].startswith(
            "PremiumBoardKB/Boards/Investor+Boards/board-eng-42/missions/mission-uuid-1001/"))
        self.assertEqual(puts[0]["edge"], "Bearer " + transport.main_access_token)
        self.assertEqual(len(downloads), 1)

        with open(self.cred_file, encoding="utf-8") as fh:
            saved = json.load(fh)
        self.assertNotIn("appsync_api_key", saved)
        cfg = submit_mission.load_json_file(self.cfg_file)
        self.assertEqual(cfg["pod_bucket"], "actionboard-kb-agent")

    def test_configured_api_key_keeps_direct_mode(self):
        with open(self.cred_file, "w", encoding="utf-8") as fh:
            json.dump({"appsync_endpoint": "https://example.appsync-api.ap-southeast-1.amazonaws.com/graphql",
                       "appsync_api_key": "da2-testapikey123"}, fh)
        saved_env = dict(os.environ)
        os.environ.pop("ACTIONBOARD_EDGE_PROXY_URL", None)
        try:
            settings = submit_mission.resolve_settings(self.cred_file, self.cfg_file)
            self.assertEqual(settings["edge_proxy"], "")
            self.assertEqual(settings["api_key"], "da2-testapikey123")
            os.environ["ACTIONBOARD_EDGE_PROXY_URL"] = "https://edge.example.dev/"
            settings = submit_mission.resolve_settings(self.cred_file, self.cfg_file)
            self.assertEqual(settings["endpoint"], "https://edge.example.dev/graphql")
            self.assertIsNone(settings["api_key"])
        finally:
            os.environ.clear()
            os.environ.update(saved_env)


if __name__ == "__main__":
    unittest.main()

