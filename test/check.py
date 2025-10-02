import os
from dotenv import load_dotenv


cwd = os.getcwd()
print(f"当前所在目录: {cwd}")

env_path = os.path.join(cwd, '.env')
print(f"检查这个路径下的文件: {env_path}")

if not os.path.exists('.env'):
    print("\n在当前位置找不到 .env 文件。")
else:
    print("\n找到了 .env 文件。")
    print("  尝试读取里面的内容...")
    
    load_dotenv()
    #加载项目根目录下.env文件中内容到环境变量os.environ
    api_key = os.getenv("GEMINI_API_KEY")

    if api_key:
        print("\n找到了'GEMINI_API_KEY'。")
    else:
        print("\n没有'GEMINI_API_KEY'。")

print("\n---结束 ---")