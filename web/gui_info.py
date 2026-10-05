"""Display login details only on an explicit local administrator command."""
import os
from settings import Settings


def main():
    if os.environ.get('ENABLE_GUI', 'false') != 'true':
        raise SystemExit('GUI is disabled; set ENABLE_GUI=true and recreate the container')
    try:
        settings = Settings.from_env(create_state=False)
    except ValueError as error:
        raise SystemExit(str(error))
    host = '[' + settings.bind + ']' if ':' in settings.bind else settings.bind
    print(f'地址: http://{host}:{settings.port}{settings.path}/')
    print(f'用户名: {settings.username}')
    print(f'密码: {settings.password}')


if __name__ == '__main__':
    main()
