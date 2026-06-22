ROLE_SPECIALIST = "specialist"
ROLE_SUPERVISOR = "supervisor"
ROLE_SUBSTITUTE = "substitute"

ROLE_LABELS = {
    ROLE_SPECIALIST: "Сотрудник стройконтроля",
    ROLE_SUPERVISOR: "Руководитель",
    ROLE_SUBSTITUTE: "Замещение",
}

SOURCE_OWNER = "owner"
SOURCE_SUPERVISOR = "supervisor"
SOURCE_SUBSTITUTE = "substitute"
SOURCE_CONTRACTOR = "contractor"

SOURCE_LABELS = {
    SOURCE_OWNER: "Пользователь",
    SOURCE_SUPERVISOR: "Руководитель",
    SOURCE_SUBSTITUTE: "Замещающий",
    SOURCE_CONTRACTOR: "Подрядчик",
}

REMARK_NOT_STARTED = "not_started"
REMARK_IN_PROGRESS = "in_progress"
REMARK_DONE = "done"
REMARK_ACCEPTED = "accepted"

REMARK_STATUS_LABELS = {
    REMARK_NOT_STARTED: "Не начато",
    REMARK_IN_PROGRESS: "В работе",
    REMARK_DONE: "Выполнено",
    REMARK_ACCEPTED: "Принято",
}

REMARK_COMPLETED = {REMARK_DONE, REMARK_ACCEPTED}

PRESCRIPTION_DONE = "Выполнено в полном объеме"
PRESCRIPTION_NO_REMARKS = "Нет замечаний"
PRESCRIPTION_NOT_STARTED = "Не исполняется"
