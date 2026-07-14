"""Source-checkout compatibility entrypoint.

Production installations can invoke the equivalent ``mako-bot`` console
command declared in ``pyproject.toml``.
"""

from src.app import bootstrap_application, main


driver = bootstrap_application()

if __name__ == "__main__":
    main()
