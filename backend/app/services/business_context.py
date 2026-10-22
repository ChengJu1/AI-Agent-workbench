"""把已落库的操作结果转换为模型可理解的业务状态说明。"""


def build_business_context(action):
    if action is None:
        return ""
    action_id = action["id"]
    status = action["status"]
    if status == "approved":
        message = (
            f"工时提交操作 {action_id} 已经由用户确认并成功执行。"
            "操作状态为 approved。不得再将这次操作描述为待确认、未提交或已取消。"
        )
        result = action.get("result")
        if isinstance(result, dict) and result.get("submission_id"):
            message += f"提交编号为 {result['submission_id']}。"
    elif status == "cancelled":
        message = (
            f"工时提交操作 {action_id} 已被用户取消。操作状态为 cancelled。"
            "该操作没有执行提交，不得声称已经提交成功。"
        )
    elif status == "failed":
        message = (
            f"工时提交操作 {action_id} 执行失败。操作状态为 failed。"
            "不得声称已经提交成功。"
        )
    else:
        return ""
    return message + "该状态只属于这个操作，不代表其他新操作已经处理。"
