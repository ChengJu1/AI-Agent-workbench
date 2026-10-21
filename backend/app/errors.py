"""定义可以安全返回给调用者的业务错误，不暴露内部异常细节。"""


class ServiceError(RuntimeError):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code

    def payload(self):
        return {"detail": str(self)}
