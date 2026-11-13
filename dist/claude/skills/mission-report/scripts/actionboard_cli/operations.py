"""ActionBoard CLI: operations."""


MUTATION_LOGIN = """
mutation Auth_login($input: Auth_LoginInput!) {
  auth_login(input: $input) {
    success
    message
    data {
      tokens {
        accessToken
        idToken
        refreshToken
        expiresIn
        tokenType
      }
      user {
        profileId
        userId
        email
        name
      }
    }
  }
}
"""


MUTATION_EXCHANGE_SOCIAL_SESSION_KEY = """
mutation Auth_exchangeSocialSessionKey($key: String!) {
  auth_exchangeSocialSessionKey(key: $key) {
    success
    message
    data {
      tokens {
        accessToken
        idToken
        refreshToken
        expiresIn
        tokenType
      }
      user {
        profileId
        userId
        email
        name
      }
    }
  }
}
"""

MUTATION_REFRESH = """
mutation Auth_refreshToken($input: Auth_RefreshTokenInput!) {
  auth_refreshToken(input: $input) {
    success
    message
    data {
      tokens {
        accessToken
        idToken
        refreshToken
        expiresIn
        tokenType
      }
    }
  }
}
"""


QUERY_ME = """
query Auth_me {
  auth_me {
    success
    message
    data {
      user {
        profileId
        userId
        email
        name
      }
    }
  }
}
"""


QUERY_MY_PODS = """
query Pods_getMyPods {
  pods_getMyPods {
    success
    message
    data {
      podId
      podName
      slug
      hostname
      bucketName
      status
      memberRole
      memberStatus
    }
  }
}
"""


MUTATION_CREATE_EXCHANGE_CODE = """
mutation Pods_createExchangeCode($podId: String!, $returnUrl: String!) {
  pods_createExchangeCode(podId: $podId, returnUrl: $returnUrl) {
    success
    message
    data {
      code
    }
  }
}
"""


MUTATION_CONSUME_EXCHANGE_CODE = """
mutation Pods_consumeExchangeCode($code: String!, $podId: String!) {
  pods_consumeExchangeCode(code: $code, podId: $podId) {
    success
    message
    data {
      token
      idToken
      accessToken
      refreshToken
      expiresIn
      userId
      email
      username
    }
  }
}
"""


QUERY_MY_BOARDS = """
query Boards_getMyBoards($podId: String) {
  boards_getMyBoards(podId: $podId) {
    success
    message
    data {
      boardId
      name
      description
      ownerId
      podId
      memberCount
      boardStatus
      boardType
      createdAt
      updatedAt
    }
  }
}
"""


QUERY_MY_BOARDS_SEARCH = """
query Boards_getMyBoards($podId: String, $searchTerm: String) {
  boards_getMyBoards(podId: $podId, searchTerm: $searchTerm) {
    success
    message
    data {
      boardId
      name
      description
      ownerId
      podId
      memberCount
      boardStatus
      boardType
      createdAt
      updatedAt
    }
  }
}
"""


QUERY_LIST_MISSIONS_BY_BOARD = """
query Assistprofile_listMissionsByBoard($boardId: ID!, $limit: Int) {
  assistprofile_listMissionsByBoard(boardId: $boardId, limit: $limit) {
    nextToken
    items {
      boardId
      missionId
      ownerProfileId
      assignedAgentProfileId
      title
      shortDescription
      startDate
      endDate
      status
      available2AAgent
      invitationMode
      totalInvited
      totalAccepted
      totalPlansSubmitted
      selectionStatus
      selectedProfileId
      selectedPlanId
      selectedAt
      createdAt
      updatedAt
      missionFolderId
      reportsSubfolderId
      totalFiles
    }
  }
}
"""


QUERY_GET_MISSION_INVITATION = """
query Assistprofile_getMissionInvitation($invitationId: ID!, $boardId: ID!) {
  assistprofile_getMissionInvitation(invitationId: $invitationId, boardId: $boardId) {
    invitationId
    missionId
    boardId
    invitedProfileId
    invitedBy
    status
    message
    expiresAt
    acceptedAt
    declinedAt
    declineReason
    planId
    planSubmittedAt
    createdAt
    updatedAt
  }
}
"""


QUERY_GET_MY_MISSION_INVITATIONS = """
query Assistprofile_getMyMissionInvitations($limit: Int) {
  assistprofile_getMyMissionInvitations(limit: $limit) {
    nextToken
    items {
      invitationId
      missionId
      boardId
      invitedProfileId
      invitedBy
      status
      message
      expiresAt
      acceptedAt
      declinedAt
      declineReason
      planId
      planSubmittedAt
      createdAt
      updatedAt
    }
  }
}
"""


QUERY_GET_MY_MISSION_INVITATIONS_BY_STATUS = """
query Assistprofile_getMyMissionInvitations($status: Assistprofile_MissionInvitationStatus, $limit: Int) {
  assistprofile_getMyMissionInvitations(status: $status, limit: $limit) {
    nextToken
    items {
      invitationId
      missionId
      boardId
      invitedProfileId
      invitedBy
      status
      message
      expiresAt
      acceptedAt
      declinedAt
      declineReason
      planId
      planSubmittedAt
      createdAt
      updatedAt
    }
  }
}
"""


MUTATION_ACCEPT_MISSION_INVITATION = """
mutation Assistprofile_acceptMissionInvitation($invitationId: ID!, $boardId: ID!) {
  assistprofile_acceptMissionInvitation(invitationId: $invitationId, boardId: $boardId) {
    invitationId
    missionId
    boardId
    invitedProfileId
    invitedBy
    status
    acceptedAt
    updatedAt
  }
}
"""


QUERY_GET_MISSION = """
query Assistprofile_getMission($boardId: ID!, $missionId: ID!) {
  assistprofile_getMission(boardId: $boardId, missionId: $missionId) {
    boardId
    missionId
    ownerProfileId
    assignedAgentProfileId
    title
    shortDescription
    startDate
    endDate
    status
    available2AAgent
    invitationMode
    totalInvited
    totalAccepted
    totalPlansSubmitted
    selectionStatus
    selectedProfileId
    selectedPlanId
    selectedAt
    createdAt
    updatedAt
    missionFolderId
    reportsSubfolderId
    totalFiles
  }
}
"""


QUERY_LIST_MISSIONS_BY_AGENT = """
query Assistprofile_listMissionsByAgent($actionAssistAgentId: ID!, $limit: Int) {
  assistprofile_listMissionsByAgent(actionAssistAgentId: $actionAssistAgentId, limit: $limit) {
    nextToken
    items {
      boardId
      missionId
      ownerProfileId
      assignedAgentProfileId
      title
      shortDescription
      startDate
      endDate
      status
      available2AAgent
      invitationMode
      selectionStatus
      selectedProfileId
      selectedPlanId
      createdAt
      updatedAt
      missionFolderId
      reportsSubfolderId
      totalFiles
    }
  }
}
"""


QUERY_GET_MISSION_PLAN = """
query Assistprofile_getMissionPlan($missionId: ID!, $planId: ID!) {
  assistprofile_getMissionPlan(missionId: $missionId, planId: $planId) {
    missionId
    planId
    boardId
    ownerProfileId
    createdByProfileId
    assignedAgentProfileId
    lastEditedByProfileId
    plan
    status
    invitationId
    submittedByProfileId
    reviewStatus
    reviewNotes
    selectionReason
    createdAt
    updatedAt
  }
}
"""


QUERY_LIST_MISSION_PLANS_BY_MISSION = """
query Assistprofile_listMissionPlansByMission($missionId: ID!, $limit: Int) {
  assistprofile_listMissionPlansByMission(missionId: $missionId, limit: $limit) {
    nextToken
    items {
      missionId
      planId
      boardId
      ownerProfileId
      createdByProfileId
      assignedAgentProfileId
      lastEditedByProfileId
      plan
      status
      invitationId
      submittedByProfileId
      reviewStatus
      reviewNotes
      selectionReason
      createdAt
      updatedAt
    }
  }
}
"""


QUERY_FILES_BY_BOARD_AND_FOLDER = """
query Filemanager_filesByBoardAndFolder($boardId: ID!, $folderId: ID!, $limit: Int) {
  filemanager_filesByBoardAndFolder(boardId: $boardId, folderId: $folderId, limit: $limit) {
    success
    message
    data {
      nextToken
      items {
        id
        boardId
        folderId
        fileName
        fileType
        fileSize
        url
        note
        tags
        s3Object {
          bucket
          key
          size
          region
          s3_uri
        }
        createdAt
        updatedAt
      }
    }
  }
}
"""


MUTATION_CREATE_MISSION = """
mutation Assistprofile_createMission($input: Assistprofile_CreateMissionInput!) {
  assistprofile_createMission(input: $input) {
    boardId
    missionId
    ownerProfileId
    assignedAgentProfileId
    title
    shortDescription
    startDate
    endDate
    status
    missionFolderId
    reportsSubfolderId
    totalFiles
    createdAt
    updatedAt
  }
}
"""


MUTATION_UPDATE_MISSION = """
mutation Assistprofile_updateMission($input: Assistprofile_UpdateMissionInput!) {
  assistprofile_updateMission(input: $input) {
    boardId
    missionId
    ownerProfileId
    assignedAgentProfileId
    title
    shortDescription
    startDate
    endDate
    status
    missionFolderId
    reportsSubfolderId
    totalFiles
    createdAt
    updatedAt
  }
}
"""


MUTATION_UPDATE_MISSION_STATUS = """
mutation Assistprofile_updateMissionStatus($input: Assistprofile_UpdateMissionStatusInput!) {
  assistprofile_updateMissionStatus(input: $input) {
    boardId
    missionId
    status
    updatedAt
  }
}
"""


CLI_FILE_TAG = "actionboard-cli"  # marks files this CLI registered, so re-submits only ever replace its own files


SYNC_MODES = ("ask", "auto", "off")


_MISSION_FILES_SELECTION = """{
    success
    message
    nextToken
    items { id fileName fileSize note tags createdAt }
  }"""


QUERY_LIST_MISSION_FILES = """
query Assistprofile_listMissionFiles($missionId: ID!, $boardId: ID!, $limit: Int) {
  assistprofile_listMissionFiles(missionId: $missionId, boardId: $boardId, limit: $limit) %s
}
""" % _MISSION_FILES_SELECTION


QUERY_LIST_MISSION_FILES_PAGE = """
query Assistprofile_listMissionFiles($missionId: ID!, $boardId: ID!, $limit: Int, $nextToken: String) {
  assistprofile_listMissionFiles(missionId: $missionId, boardId: $boardId, limit: $limit, nextToken: $nextToken) %s
}
""" % _MISSION_FILES_SELECTION


MUTATION_DELETE_MISSION_FILE = """
mutation Assistprofile_deleteMissionFile($missionId: ID!, $boardId: ID!, $fileId: ID!) {
  assistprofile_deleteMissionFile(missionId: $missionId, boardId: $boardId, fileId: $fileId)
}
"""


MUTATION_CREATE_MISSION_COMMENT = """
mutation Assistprofile_createMissionComment($input: Assistprofile_CreateMissionCommentInput!) {
  assistprofile_createMissionComment(input: $input) {
    commentId
    missionId
    boardId
    text
  }
}
"""


MUTATION_DELETE_MISSION = """
mutation Assistprofile_deleteMission($boardId: ID!, $missionId: ID!) {
  assistprofile_deleteMission(boardId: $boardId, missionId: $missionId)
}
"""


MUTATION_CREATE_MISSION_PLAN = """
mutation Assistprofile_createMissionPlan($input: Assistprofile_CreateMissionPlanInput!) {
  assistprofile_createMissionPlan(input: $input) {
    missionId
    planId
    boardId
    ownerProfileId
    createdByProfileId
    assignedAgentProfileId
    lastEditedByProfileId
    plan
    status
    invitationId
    submittedByProfileId
    reviewStatus
    createdAt
    updatedAt
  }
}
"""


MUTATION_UPDATE_MISSION_PLAN = """
mutation Assistprofile_updateMissionPlan($input: Assistprofile_UpdateMissionPlanInput!) {
  assistprofile_updateMissionPlan(input: $input) {
    missionId
    planId
    boardId
    ownerProfileId
    createdByProfileId
    assignedAgentProfileId
    lastEditedByProfileId
    plan
    status
    updatedAt
  }
}
"""


MUTATION_SUBMIT_MISSION_PLAN = """
mutation Assistprofile_submitMissionPlan($input: Assistprofile_SubmitMissionPlanInput!) {
  assistprofile_submitMissionPlan(input: $input) {
    missionId
    planId
    boardId
    ownerProfileId
    createdByProfileId
    submittedByProfileId
    assignedAgentProfileId
    invitationId
    plan
    status
    reviewStatus
    createdAt
    updatedAt
  }
}
"""


MUTATION_SUBMIT_REPORTS = """
mutation Assistprofile_submitReports($input: Assistprofile_SubmitReportsInput!) {
  assistprofile_submitReports(input: $input) {
    success
    message
    totalFiles
    files {
      id
      boardId
      folderId
      fileName
      fileType
      fileSize
      url
      note
      tags
      createdAt
      updatedAt
    }
  }
}
"""


QUERY_FOLDERS_BY_BOARD = """
query Filemanager_foldersByBoardIdIndex($boardId: ID!, $first: Int) {
  filemanager_foldersByBoardIdIndex(boardId: $boardId, first: $first) {
    success
    message
    data {
      items {
        id
        boardId
        folderName
        parentFolderId
      }
    }
  }
}
"""


MUTATION_CREATE_FOLDER = """
mutation Filemanager_createFolder($input: Filemanager_CreateFileManagerFolderInput!) {
  filemanager_createFolder(input: $input) {
    success
    message
    data {
      id
      boardId
      folderName
      parentFolderId
    }
  }
}
"""


MUTATION_CREATE_FILE = """
mutation Filemanager_createFile($input: Filemanager_CreateFileManagerFileInput!) {
  filemanager_createFile(input: $input) {
    success
    message
    data {
      id
      boardId
      folderId
      fileName
      fileType
      fileSize
      url
    }
  }
}
"""


