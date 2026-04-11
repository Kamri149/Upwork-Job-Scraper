from pydantic import BaseModel


class ProxyConfig(BaseModel):
    host: str
    port: int
    username: str
    password: str

    def to_proxy_url(self) -> str:
        return f"http://{self.username}:{self.password}@{self.host}:{self.port}"

    def to_curl_cffi_dict(self) -> dict:
        url = self.to_proxy_url()
        return {"http": url, "https": url}
