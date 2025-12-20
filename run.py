import sys
import os
from streamlit.web import cli as stcli

if __name__ == '__main__':
    # 获取当前 app.py 的绝对路径
    sys.argv = ["streamlit", "run", "app.py", "--global.developmentMode=false"]
    sys.exit(stcli.main())