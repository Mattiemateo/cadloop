class CadLoopError(Exception):
    def __init__(self, code: str, message: str, **details):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details

    def as_dict(self):
        return {"status": "error", "code": self.code, "message": self.message,
                "details": self.details}
