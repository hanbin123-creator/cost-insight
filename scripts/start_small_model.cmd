@echo off
REM 启动本地小模型服务（Qwen3.5-9B UD-Q2_K_XL · llama.cpp · CPU 推理）
REM 推理引擎与模型文件不入 git（合计约 4GB），获取方式见 README「可选本地小模型」。
REM 服务未启动时：分类调用失败 → 路由规则层兜底（三层架构第 2 层，服务不炸）。
setlocal
set LLAMA_DIR=%~dp0..\..\_small_model
if not exist "%LLAMA_DIR%\llama-bin\llama-server.exe" (
  echo [缺失] 未找到 llama-server.exe：%LLAMA_DIR%\llama-bin\
  echo 请按 README「可选本地小模型」一节放置推理引擎。
  exit /b 1
)
if not exist "%LLAMA_DIR%\qwen35-9b-q2.gguf" (
  echo [缺失] 未找到模型文件 qwen35-9b-q2.gguf（约 3.8GB）
  echo 请按 README「可选本地小模型」一节下载模型。
  exit /b 1
)
echo 启动小模型服务：Qwen3.5-9B UD-Q2_K_XL @ http://127.0.0.1:8001
echo 说明：--chat-template-kwargs 关闭思考模式（Qwen3.5 小模型默认思考会耗尽输出预算，开发日志 37）
echo 关闭本窗口即停止服务。
"%LLAMA_DIR%\llama-bin\llama-server.exe" -m "%LLAMA_DIR%\qwen35-9b-q2.gguf" --alias qwen3.5-9b-local --port 8001 --ctx-size 4096 --threads 8 --temp 0.0 --jinja --chat-template-kwargs "{\"enable_thinking\":false}"
