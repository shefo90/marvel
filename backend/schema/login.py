"""Login contracts.

Zero logic. Pydantic models only.

``token_pair`` is the single shape both staff and shopper login return, and the
shape refresh rotation returns too — a client that can read one can read all
three. ``scope`` is echoed back because the two token families are not
interchangeable (``services.create_token`` verifies the claim on decode), so a
client holding both must be able to tell them apart without decoding a JWT.
"""

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class login_request(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class token_pair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    # Seconds until the access token expires. The refresh token outlives it.
    expires_in: int
    scope: str
