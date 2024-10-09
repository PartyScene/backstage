from dataclasses import dataclass
from pydantic import Field

@dataclass
class FormIn:
    """
    Register user request
    """
    email: str = Field(title="E-mail", description="E-mail address of registering account.")
    first_name: str = Field(title="E-mail", description="E-mail address of registering account.")
    last_name: str = Field(title="Last Name", description="E-mail address of registering account.")
    password: str = Field(title="Password", description="E-mail address of registering account.")
    
@dataclass
class LoginForm:
    """
    Login user request
    """
    email: str = Field(title="E-mail", description="E-mail Credential.")
    password: str = Field(title="Password", description="Password Credential")
    
