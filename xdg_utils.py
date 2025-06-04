import os
from pathlib import Path
import sys

def get_xdg_data_dir() -> Path:
    """
    Gets the XDG data directory for the application.

    1. Tries XDG_DATA_HOME environment variable.
    2. Defaults to ~/.local/share if XDG_DATA_HOME is not set/empty.
    3. Appends 'dtb_viewer' to create the application-specific directory.
    4. Creates the directory if it doesn't exist.
    Returns:
        Path: The Path object for the application's data directory.
    """
    # Ensure APP_NAME is defined or passed as an argument for better reusability
    # For now, keeping 'dtb_viewer' as per original function for this step
    app_name = "dtb_viewer"

    xdg_data_home_str = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home_str and xdg_data_home_str.strip():
        base_path = Path(xdg_data_home_str)
    else:
        base_path = Path.home() / ".local" / "share"

    app_data_dir = base_path / app_name

    try:
        os.makedirs(app_data_dir, exist_ok=True)
    except OSError as e:
        # Handle potential errors like permission issues, though exist_ok=True handles existing directory
        print(f"Error creating XDG data directory {app_data_dir}: {e}", file=sys.stderr)
        # Fallback or raise error depending on how critical this directory is.
        # For now, we'll let it proceed, but an error message is printed.
        # If the directory is absolutely critical, an exception should be raised here.
        pass # Or raise an exception if the directory is critical

    return app_data_dir
