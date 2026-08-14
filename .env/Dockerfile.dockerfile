# 使用 Python 3.10 轻量镜像
FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖（可选，如果有需要编译的包）
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制整个项目
COPY . .

# 暴露端口
EXPOSE 8000

# 启动命令（指向 app.main 中的 app 实例）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]