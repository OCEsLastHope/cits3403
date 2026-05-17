from ..blueprints import main_bp

# Import modules for side-effect route/socket registration.
from . import auth  # noqa: F401
from . import dashboard  # noqa: F401
from . import events  # noqa: F401
from . import invitations  # noqa: F401
from . import landing  # noqa: F401
from . import matches  # noqa: F401
from . import messages  # noqa: F401
from . import notifications  # noqa: F401
from . import onboarding  # noqa: F401
from . import people  # noqa: F401
from . import profile  # noqa: F401
from . import realtime  # noqa: F401
