import threading
import pyaudio
import dashscope
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult
import openai
import tkinter as tk
from tkinter import messagebox, StringVar, scrolledtext
import json
import re
import os  # 增加模块用于文件操作
# 初始化API密钥

# 初始化 API 密钥
def get_key(filename):
    with open(filename, 'r') as file:
        lines = file.readlines()
        dashscope_key = lines[0].strip()
        openai_key = lines[1].strip()
    return dashscope_key, openai_key

# 全局变量
dashscope.api_key, openai.api_key = get_key('key.txt')
openai.api_base = "https://api.chatfire.cn/v1"
text_buffer = ""
state = "stopped"
recognition_condition = threading.Condition()
is_recognition_active = False
current_question_index = 0
questions = []



# 自定义回调类
class Callback(RecognitionCallback):
    def __init__(self):
        super().__init__()  # 调用父类构造函数
        self.parent = None  # 初始化 parent 属性

    # 设置 parent 属性
    def set_parent(self, parent):
        """
        设置 parent 属性，用于关联外部对象。
        """
        self.parent = parent

    # 处理语音识别结果
    def on_event(self, result: RecognitionResult) -> None:
        """
        处理语音识别结果，仅显示完整句子。
        """
        if not self.parent:
            print("Callback parent not set.")
            return

        try:
            sentence = result.get_sentence()  # 获取句子
            if sentence and RecognitionResult.is_sentence_end(sentence):
                text = sentence.get("text", "")  # 获取句子文本
                if text:
                    # 将最终句子填入输入框
                    self.parent.root.after(0, self.parent.process_voice_input, text)
        except Exception as e:
            print(f"Error processing recognition result: {e}")

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("教学与考核系统")
        self.teaching_button = tk.Button(root, text="教学模式", command=self.show_teaching_mode)
        self.exam_button = tk.Button(root, text="考核模式", command=self.start_exam_mode)
        self.record_button = tk.Button(root, text="查看聊天记录", command=self.view_chat_history)  # 聊天记录按钮
        self.wrong_button = tk.Button(root, text="错题本", command=self.view_wrong_book)  # 错题本按钮
        self.teaching_button.pack(pady=20)
        self.exam_button.pack(pady=20)
        self.record_button.pack(pady=20)
        self.wrong_button.pack(pady=20)
        self.user_answers = {}  # 用于保存用户的答案
        self.conversation_history = []  # 用于保存对话历史
        self.evaluation_results = {}  # 用于保存评判结果
        self.current_mode = None  # 初始化为 None
        self.current_dialog_key = None  # 当前对话的键
        # 文件路径初始化
        self.chat_record_path = "discuss.json"
        self.wrong_question_path = "wrong.json"
        self.state = "stopped"  # 默认语音输入的状态为停止
        self.is_recognition_active = False  # 用于语音识别的标志

    # 保存聊天记录到本地
    def save_chat_history(self):
        if not self.conversation_history:
            print("再见")
            return
        try:
            # 加载现有记录
            if os.path.exists(self.chat_record_path):
                with open(self.chat_record_path, "r", encoding="utf-8") as file:
                    existing_data = json.load(file)
            else:
                existing_data = {}
            # 确保 current_dialog_key 存在
            if not hasattr(self, "current_dialog_key") or not self.current_dialog_key:
                # 创建新对话记录
                dialog_key = f"dialog{len(existing_data) + 1}"
                dialog_data = {"num": 0}
                self.current_dialog_key = dialog_key
            else:
                # 获取当前对话记录
                dialog_key = self.current_dialog_key
                dialog_data = existing_data.get(dialog_key, {"num": 0})

            # 获取对话已存在的条数
            existing_num = dialog_data["num"]

            # 将当前对话内容追加到记录中
            for i in range(existing_num, len(self.conversation_history) // 2):
                dialog_data[f"Q{i + 1}"] = self.conversation_history[i * 2]["content"]
                dialog_data[f"A{i + 1}"] = self.conversation_history[i * 2 + 1]["content"]
                dialog_data["num"] += 1
                print(f"Q{i + 1}: {dialog_data[f'Q{i + 1}']}")
                print(f"A{i + 1}: {dialog_data[f'A{i + 1}']}")
            # 更新到 existing_data
            existing_data[dialog_key] = dialog_data

            # 保存到文件
            with open(self.chat_record_path, "w", encoding="utf-8") as file:
                json.dump(existing_data, file, ensure_ascii=False, indent=4)
            print("existing_data:", existing_data)

        except Exception as e:
            messagebox.showerror("错误", f"保存聊天记录出错: {e}")

    # 退出时保存聊天记录
    def on_close(self):
        # 保存聊天记录
        self.save_chat_history()
        self.root.destroy()

        # 打开指定对话的详细记录

    # 打开指定对话的详细记录
    def open_chat(self, dialog_key):
        # 读取聊天记录文件
        try:
            with open(self.chat_record_path, "r", encoding="utf-8") as file:
                chat_data = json.load(file)
        except (json.JSONDecodeError, FileNotFoundError):
            messagebox.showerror("错误", "聊天记录文件格式错误或不存在")
            return

        # 获取指定对话记录
        dialog = chat_data.get(dialog_key, {})
        if not dialog:
            messagebox.showerror("错误", "未找到指定对话")
            return

        # 保存当前对话标识
        self.current_dialog_key = dialog_key

        # 清空屏幕
        self.clear_screen()

        # 显示对话记录
        self.chat_display = scrolledtext.ScrolledText(self.root, height=20, width=80, state='normal', wrap='word')
        for i in range(1, dialog["num"] + 1):
            self.chat_display.insert(tk.END, f"{dialog.get(f'Q{i}', '')}\n {dialog.get(f'A{i}', '')}\n\n")
        self.chat_display.config(state='disabled')
        self.chat_display.pack(pady=10)

        # 保存当前对话到内存中以继续聊天
        self.conversation_history = []
        for i in range(1, dialog["num"] + 1):
            if dialog.get(f"Q{i}"):
                self.conversation_history.append({"role": "user", "content": dialog[f"Q{i}"]})
            if dialog.get(f"A{i}"):
                self.conversation_history.append({"role": "assistant", "content": dialog[f"A{i}"]})

        # 创建消息输入框
        self.message_entry = tk.Entry(self.root, width=70)
        self.message_entry.pack(pady=5)

        # 发送消息按钮
        send_btn = tk.Button(self.root, text="发送", command=self.send_message)
        send_btn.pack(pady=5)

        # 返回聊天记录按钮，加入保存逻辑
        return_btn = tk.Button(
            self.root,
            text="返回聊天记录",
            command=lambda: [self.save_chat_history(), self.view_chat_history()]
        )
        return_btn.pack(pady=10)

    # 查看聊天记录
    def view_chat_history(self):
        """
        显示聊天记录页面，按钮内容为第一条提问的前 20 个字符。
        每条记录旁添加一个删除按钮（红叉）。
        """
        self.clear_screen()

        # 容器框架
        container = tk.Frame(self.root, bg="white", width=400, height=600)
        container.pack(fill="both", expand=True, padx=10, pady=10)

        # Canvas 和 Scrollbar
        history_canvas = tk.Canvas(container, bg="white", width=400, height=600)
        scrollbar = tk.Scrollbar(container, orient="vertical", command=history_canvas.yview)
        scrollable_frame = tk.Frame(history_canvas, bg="white", width=400, height=600)

        # 配置 Canvas
        scrollable_frame.bind(
            "<Configure>",
            lambda e: history_canvas.configure(scrollregion=history_canvas.bbox("all"))
        )
        history_canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        history_canvas.configure(yscrollcommand=scrollbar.set)

        # 布局 Canvas 和 Scrollbar
        history_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 读取聊天记录文件
        try:
            with open(self.chat_record_path, "r", encoding="utf-8") as file:
                chat_data = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            chat_data = {}

        # 显示聊天记录
        if not chat_data:
            no_data_label = tk.Label(scrollable_frame, text="暂无聊天记录", bg="white", font=("Arial", 10))
            no_data_label.pack(pady=10)
        else:
            for dialog_key, dialog_content in chat_data.items():
                # 获取第一条提问并截取前 20 个字符
                first_question = dialog_content.get("Q1", "无提问内容")[:20]

                # 按钮框架
                button_frame = tk.Frame(scrollable_frame, bg="white")
                button_frame.pack(fill="x", pady=5, padx=5)

                # 聊天记录按钮
                dialog_button = tk.Button(
                    button_frame,
                    text=first_question,
                    command=lambda dk=dialog_key: self.view_chat_detail(chat_data, dk),
                    width=25
                )
                dialog_button.pack(side="left", padx=5)

                # 删除按钮
                delete_btn = tk.Button(
                    button_frame,
                    text="✖",  # 红叉符号
                    command=lambda dk=dialog_key: self.delete_chat_record(chat_data, dk),
                    bg="red",
                    fg="white",
                    font=("Arial", 10, "bold"),
                    width=2
                )
                delete_btn.pack(side="right", padx=5)

        # 返回主菜单按钮
        return_btn = tk.Button(self.root, text="返回主菜单", command=self.return_to_main)
        return_btn.pack(pady=10)

    # 删除指定的聊天记录
    def delete_chat_record(self, chat_data, dialog_key):
        """
        删除指定的聊天记录。
        """
        try:
            if dialog_key in chat_data:
                del chat_data[dialog_key]  # 删除指定聊天记录

                # 更新文件内容
                with open(self.chat_record_path, "w", encoding="utf-8") as file:
                    json.dump(chat_data, file, ensure_ascii=False, indent=4)

                messagebox.showinfo("提示", "聊天记录已删除")
            else:
                messagebox.showerror("错误", "未找到指定聊天记录")

            # 刷新聊天记录界面
            self.view_chat_history()
        except Exception as e:
            print(f"delete_chat_record: Error occurred - {e}")
            messagebox.showerror("错误", f"删除聊天记录时出错: {e}")

    # 查看具体聊天记录
    def view_chat_detail(self, chat_data, dialog_key):
        """
        查看具体聊天记录，宽度固定为 800，并支持滚动。
        """
        self.clear_screen()

        # 获取指定对话的内容
        dialog = chat_data.get(dialog_key, {})
        if not dialog:
            messagebox.showerror("错误", "未找到指定对话")
            self.view_chat_history()
            return

        # 容器框架
        container = tk.Frame(self.root, bg="white", width=00)
        container.pack(fill="both", expand=True, padx=10, pady=10)

        # Canvas 和 Scrollbar
        detail_canvas = tk.Canvas(container, bg="white", width=800, height=600)
        scrollbar = tk.Scrollbar(container, orient="vertical", command=detail_canvas.yview)
        scrollable_frame = tk.Frame(detail_canvas, bg="white", width=800)

        # 配置 Canvas
        scrollable_frame.bind(
            "<Configure>",
            lambda e: detail_canvas.configure(scrollregion=detail_canvas.bbox("all"))
        )
        detail_canvas.create_window((0, 0), window=scrollable_frame, anchor="nw", width=800)
        detail_canvas.configure(yscrollcommand=scrollbar.set)

        # 布局 Canvas 和 Scrollbar
        detail_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 显示具体对话内容
        for i in range(1, dialog["num"] + 1):
            # 显示用户提问
            user_question = dialog.get(f"Q{i}", "")
            if user_question:
                self._add_message_with_avatar(scrollable_frame, user_question, role="user")

            # 显示 AI 回答
            ai_answer = dialog.get(f"A{i}", "")
            if ai_answer:
                self._add_message_with_avatar(scrollable_frame, ai_answer, role="assistant")

        # 按钮框架
        button_frame = tk.Frame(self.root)
        button_frame.pack(pady=10)

        # 返回聊天记录按钮
        return_btn = tk.Button(button_frame, text="返回聊天记录", command=self.view_chat_history)
        return_btn.pack(side=tk.LEFT, padx=5)

        # 继续对话按钮
        continue_btn = tk.Button(
            button_frame,
            text="继续对话",
            command=lambda: self.continue_conversation(dialog)
        )
        continue_btn.pack(side=tk.LEFT, padx=5)

    # 继续对话
    def continue_conversation(self, dialog):
        """
        加载指定聊天记录，进入继续对话模式。
        """
        # 加载历史记录到 self.conversation_history
        self.conversation_history = []
        for i in range(1, dialog["num"] + 1):
            user_question = dialog.get(f"Q{i}", "")
            ai_answer = dialog.get(f"A{i}", "")
            if user_question:
                self.conversation_history.append({"role": "user", "content": user_question})
            if ai_answer:
                self.conversation_history.append({"role": "assistant", "content": ai_answer})

        # 显示教学模式界面（正常聊天界面）
        self.show_teaching_mode()

        # 将历史记录加载到聊天框
        for record in self.conversation_history:
            role = "user" if record["role"] == "user" else "assistant"
            self.update_chat_display(f"{record['content']}", role=role)

    # 在指定父容器中添加带头像的消息，按比例对齐和宽度显示
    def _add_message_with_avatar(self, parent, message, role="user"):
        """
        在指定父容器中添加带头像的消息，按比例对齐和宽度显示。
        AI 消息占左 2/3，用户消息占右 2/3。
        """
        # 父框架：按角色对齐
        message_frame = tk.Frame(parent, bg="white")
        message_frame.pack(
            fill="x",
            pady=5,
            padx=10,
            anchor="w" if role == "assistant" else "e"  # AI 左对齐，用户右对齐
        )

        # 添加头像
        avatar_canvas = tk.Canvas(message_frame, width=40, height=40, bg="white", highlightthickness=0)
        avatar_canvas.create_oval(5, 5, 35, 35, fill="red" if role == "assistant" else "yellow", outline="")
        avatar_canvas.create_text(
            20, 20, text="AI" if role == "assistant" else "我", fill="white" if role == "assistant" else "black", font=("microsoftyahei", 10, "bold")
        )
        avatar_canvas.pack(side="top", anchor="w" if role == "assistant" else "e")  # 顶部对齐

        # 消息文本框：按比例限制宽度
        text_color = "green" if role == "assistant" else "blue"
        text_width = int(800 * 2 / 3)  # 2/3 的总宽度（假设窗口宽度为 800）
        text_label = tk.Label(
            message_frame,
            text=message,
            wraplength=text_width,
            justify="left" if role == "assistant" else "right",
            bg="white",
            fg=text_color,
            font=("microsoftyahei", 10)
        )
        text_label.pack(side="left" if role == "assistant" else "right", padx=5)

    # 显示错题详情
    def view_question_detail(self, wrong_data, question_key):
        """
        显示错题详情，包括题目描述、选项、用户答案、正确答案和解释。
        限制界面宽度，超出内容自动换行。
        """
        self.clear_screen()

        # 获取错题详情
        question = wrong_data[question_key]

        # 标题
        tk.Label(self.root, text="错题详情", font=("microsoftyahei", 16, "bold")).pack(pady=20)

        # 显示题目描述
        tk.Label(
            self.root,
            text=f"题目描述: {question['description']}",
            wraplength=700,  # 限制宽度为 700 像素
            justify="left",  # 左对齐
            font=("microsoftyahei", 12)
        ).pack(pady=10)

        # 如果是选择题，显示选项
        if question["type"] == "选择" and "options" in question:
            options = question["options"].split(",")
            user_answer = question.get("user_answer", "").strip()
            correct_answer = question.get("answer", "").strip()

            # 遍历选项并显示
            for option in options:
                opt_key, opt_text = option.split(":")
                color = "red" if opt_key.strip() == user_answer else "green" if opt_key.strip() == correct_answer else "black"
                tk.Label(
                    self.root,
                    text=f"{opt_key}: {opt_text}",
                    fg=color,
                    font=("microsoftyahei", 10, "bold" if color in ["red", "green"] else "normal"),
                ).pack(anchor="w", padx=20)

        # 显示用户答案和正确答案，限制宽度
        tk.Label(
            self.root,
            text=f"你的答案: {question['user_answer']}",
            wraplength=700,  # 限制宽度为 700 像素
            justify="left",
            fg="red",
            font=("microsoftyahei", 15)
        ).pack(pady=5)

        tk.Label(
            self.root,
            text=f"正确答案: {question['answer']}",
            wraplength=700,  # 限制宽度为 700 像素
            justify="left",
            fg="green",
            font=("microsoftyahei", 15)
        ).pack(pady=5)

        # 显示答案解释，限制宽度
        tk.Label(
            self.root,
            text=f"答案解释: {question['explanation']}",
            wraplength=700,  # 限制宽度为 700 像素
            justify="left",
            font=("microsoftyahei", 12)
        ).pack(pady=10)

        # 删除错题按钮
        delete_btn = tk.Button(
            self.root,
            text="删除此错题",
            command=lambda: self.delete_wrong_question(wrong_data, question_key),
            bg="red",
            fg="white",
            font=("microsoftyahei", 12)
        )
        delete_btn.pack(pady=10)

        # 返回对应类型题目列表
        return_btn = tk.Button(
            self.root,
            text="返回列表",
            command=lambda: self.view_wrong_type(question["type"]),
            font=("microsoftyahei", 12)
        )
        return_btn.pack(pady=10)

    # 删除指定错题
    def delete_wrong_question(self, wrong_data, question_key):
        """
        删除指定错题并刷新错题本界面。
        """
        try:
            if question_key in wrong_data:
                del wrong_data[question_key]  # 删除指定错题

            # 更新文件内容
            with open(self.wrong_question_path, "w", encoding="utf-8") as file:
                json.dump(wrong_data, file, ensure_ascii=False, indent=4)

            messagebox.showinfo("提示", "错题已删除")

            # 检查是否还有错题
            if not wrong_data:
                self.return_to_main()  # 如果没有错题，返回主菜单
            else:
                self.view_wrong_book()  # 刷新错题本界面
        except Exception as e:
            print(f"delete_wrong_question: Error occurred - {e}")
            messagebox.showerror("错误", f"删除错题时出错: {e}")

    # 保存错题到本地
    def save_wrong_questions(self):
        # 文件路径
        wrong_file = "wrong.json"

        # 初始化错题记录
        if os.path.exists(wrong_file):
            try:
                with open(wrong_file, "r", encoding="utf-8") as file:
                    existing_data = json.load(file)
            except (json.JSONDecodeError, FileNotFoundError):
                existing_data = {}
        else:
            existing_data = {}

        # 确定当前错题的起始编号
        current_count = len(existing_data)
        new_wrong_data = {}

        # 收集错题数据
        for evaluation_index, evaluation in self.evaluation_results.items():
            if evaluation["result"] != "正确":  # 只保存错误的题目
                question = questions[evaluation_index]
                current_count += 1
                new_wrong_data[str(current_count)] = {
                    "type": question["type"],
                    "description": question["description"],
                    "options": question.get("option", ""),  # 保存选项
                    "answer": question["answer"],
                    "user_answer": self.user_answers.get(evaluation_index, ""),
                    "explanation": question.get("explanation", "")
                }

        # 如果没有新错题，直接返回
        if not new_wrong_data:
            print("save_wrong_questions: No new wrong questions to save.")
            return

        # 合并新错题
        existing_data.update(new_wrong_data)

        # 保存到文件
        try:
            with open(wrong_file, "w", encoding="utf-8") as file:
                json.dump(existing_data, file, ensure_ascii=False, indent=4)
            print("save_wrong_questions: Wrong questions saved successfully.")
        except Exception as e:
            print(f"save_wrong_questions: Error occurred - {e}")
            messagebox.showerror("错误", f"保存错题时出错: {e}")

    # 查看错题本
    def view_wrong_book(self):
        """
        显示错题本主界面，提供选择题、填空题、简答题的入口。
        """
        self.clear_screen()

        # 标题
        tk.Label(self.root, text="错题本", font=("microsoftyahei", 16, "bold")).pack(pady=20)

        # 选择题按钮
        choice_btn = tk.Button(
            self.root,
            text="选择题",
            command=lambda: self.view_wrong_type("选择"),
            font=("microsoftyahei", 12),
            width=20,
            height=2
        )
        choice_btn.pack(pady=10)

        # 填空题按钮
        fill_btn = tk.Button(
            self.root,
            text="填空题",
            command=lambda: self.view_wrong_type("填空"),
            font=("microsoftyahei", 12),
            width=20,
            height=2
        )
        fill_btn.pack(pady=10)

        # 简答题按钮
        open_btn = tk.Button(
            self.root,
            text="简答题",
            command=lambda: self.view_wrong_type("简答"),
            font=("microsoftyahei", 12),
            width=20,
            height=2
        )
        open_btn.pack(pady=10)

        # 返回主菜单按钮
        return_btn = tk.Button(self.root, text="返回主菜单", command=self.return_to_main, font=("microsoftyahei", 12))
        return_btn.pack(pady=20)

    # 查看指定类型的错题
    def view_wrong_type(self, question_type):
        """
        显示指定类型的错题列表。
        """
        self.clear_screen()

        # 读取错题记录
        try:
            with open(self.wrong_question_path, "r", encoding="utf-8") as file:
                wrong_data = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            wrong_data = {}

        # 筛选对应类型的错题
        filtered_questions = {
            key: question for key, question in wrong_data.items() if question["type"] == question_type
        }

        # 显示标题
        tk.Label(self.root, text=f"{question_type} 错题", font=("microsoftyahei", 16, "bold")).pack(pady=20)

        # 显示题目列表
        if not filtered_questions:
            tk.Label(self.root, text="暂无错题", font=("microsoftyahei", 12)).pack(pady=10)
        else:
            for question_key, question in filtered_questions.items():
                # 按钮内容为题目描述的前 20 个字符
                description_preview = question["description"][:20]
                question_btn = tk.Button(
                    self.root,
                    text=description_preview,
                    command=lambda qk=question_key: self.view_question_detail(wrong_data, qk),
                    font=("microsoftyahei", 12),
                    width=40,
                    height=2
                )
                question_btn.pack(pady=5)

        # 返回错题本主界面按钮
        return_btn = tk.Button(
            self.root,
            text="返回错题本",
            command=self.view_wrong_book,
            font=("microsoftyahei", 12)
        )
        return_btn.pack(pady=20)

    # 清除错题记录
    def clear_wrong_questions(self):
        if os.path.exists(self.wrong_question_path):
            os.remove(self.wrong_question_path)
        messagebox.showinfo("提示", "错题本已清空")
        self.return_to_main()

    # 返回主菜单
    def return_to_main(self):
        # 确保保存当前对话记录
        if hasattr(self, "current_mode") and self.current_mode == "teaching":
            self.save_chat_history()  # 调用保存方法
        elif hasattr(self, "current_mode") and self.current_mode == "exam":
            self.save_wrong_questions()  # 考试模式保存错题

        # 清屏并返回主界面
        self.clear_screen()
        self.__init__(self.root)

    # 教学模式界面
    def show_teaching_mode(self):
        """
        显示教学模式界面，设置消息框宽度为 800，AI 和用户消息按 2/3 对齐。
        """
        self.clear_screen()
        self.current_mode = "teaching"

        # 容器框架
        container = tk.Frame(self.root, bg="white", width=800, height=600)
        container.pack(fill="both", expand=True, padx=10, pady=10)

        # Canvas 和 Scrollbar
        self.chat_canvas = tk.Canvas(container, bg="white", width=800, height=600)
        scrollbar = tk.Scrollbar(container, orient="vertical", command=self.chat_canvas.yview)
        self.chat_display_frame = tk.Frame(self.chat_canvas, bg="white", width=800, height=600)

        # 配置 Canvas
        self.chat_display_frame.bind(
            "<Configure>",
            lambda e: self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))
        )
        self.chat_canvas.create_window((0, 0), window=self.chat_display_frame, anchor="nw", width=780)
        self.chat_canvas.configure(yscrollcommand=scrollbar.set)

        # 布局 Canvas 和 Scrollbar
        self.chat_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 消息输入框
        self.message_entry = tk.Entry(self.root, width=70)
        self.message_entry.pack(pady=5)

        # 按钮框架
        button_frame = tk.Frame(self.root)
        button_frame.pack(pady=5)

        # 发送按钮
        send_btn = tk.Button(button_frame, text="发送", command=self.send_message)
        send_btn.pack(side=tk.LEFT, padx=5)

        # 语音输入按钮
        self.start_voice_btn = tk.Button(button_frame, text="语音输入", command=self.toggle_voice_input)
        self.start_voice_btn.pack(side=tk.LEFT, padx=5)

        # 返回主菜单按钮
        return_btn = tk.Button(button_frame, text="返回主菜单", command=self.return_to_main)
        return_btn.pack(side=tk.LEFT, padx=5)

    # 语音输入功能的启动与停止
    def toggle_voice_input(self):
        """
        切换语音输入功能的启动与停止。
        """
        if self.state == "stopped":
            self.state = "running"
            threading.Thread(target=self.start_recognition).start()
            self.start_voice_btn.config(text="停止语音输入")
        elif self.state == "running":
            self.state = "stopped"
            self.start_voice_btn.config(text="语音输入")

    # 开始语音识别，将语音实时转化为文本
    def start_recognition(self):
        """
        开始语音识别，将语音实时转化为文本。
        """
        import pyaudio
        from dashscope.audio.asr import Recognition

        try:
            # 初始化麦克风和音频流
            mic = pyaudio.PyAudio()
            stream = mic.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=3200)

            # 创建识别实例和回调
            callback = Callback()
            callback.set_parent(self)  # 设置回调的 parent

            recognition = Recognition(
                model="paraformer-realtime-v2",
                format="pcm",
                sample_rate=16000,
                callback=callback
            )
            recognition.start()

            self.is_recognition_active = True
            while self.state == "running":
                # 发送音频数据
                data = stream.read(3200, exception_on_overflow=False)
                recognition.send_audio_frame(data)

        except Exception as e:
            print(f"语音识别初始化失败: {e}")
            messagebox.showerror("错误", f"语音识别初始化失败: {e}")

        finally:
            # 停止流和释放资源
            if self.is_recognition_active:
                recognition.stop()
                self.is_recognition_active = False
            stream.stop_stream()
            stream.close()
            mic.terminate()

    # 将最终识别的文本显示在输入框中
    def process_voice_input(self, voice_text):
        """
        将最终识别的文本显示在输入框中。
        """
        if self.message_entry:
            self.message_entry.delete(0, tk.END)  # 清空输入框
            self.message_entry.insert(tk.END, voice_text)  # 插入最终结果

    # 发送用户消息并调用 OpenAI API 获取回复
    def send_message(self):
        user_message = self.message_entry.get().strip()
        if not user_message:
            return

        # 清空输入框
        self.message_entry.delete(0, tk.END)

        # 更新对话历史并显示用户的提问
        self.conversation_history.append({"role": "user", "content": user_message})
        self.update_chat_display(f"{user_message}", role="user")

        # 调用 OpenAI API 获取回复
        try:
            response = openai.ChatCompletion.create(
                model="gpt-4o",
                messages=self.conversation_history
            )
            assistant_message = response['choices'][0]['message']['content']

            # 更新对话历史并显示 AI 的回答
            self.conversation_history.append({"role": "assistant", "content": assistant_message})
            self.update_chat_display(f"{assistant_message}", role="assistant")
        except Exception as e:
            messagebox.showerror("错误", f"调用 OpenAI API 出错: {e}")

    # 更新聊天记录显示
    def update_chat_display(self, message, role="user"):
        """
        更新聊天记录显示，并刷新滑框滚动区域。
        """
        if not hasattr(self, "chat_display_frame"):
            print("Error: Chat display frame not initialized.")
            return

        # 调用 `_add_message_with_avatar` 动态添加消息
        self._add_message_with_avatar(self.chat_display_frame, message, role)

        # 刷新滑框滚动区域
        self.chat_canvas.update_idletasks()
        self.chat_canvas.yview_moveto(1.0)  # 滚动到底部

    # 调整聊天框宽度
    def adjust_chat_frame_width(self, message):
        """
        根据消息内容动态调整聊天框宽度。
        """
        # 计算消息的宽度（按字符长度计算，大致换算为像素宽度）
        char_width = 8  # 每个字符约占 8 像素
        max_width = 600  # 聊天框最大宽度
        min_width = 200  # 聊天框最小宽度

        message_width = len(message) * char_width
        frame_width = min(max(message_width, min_width), max_width)

        # 调整聊天框宽度
        self.chat_display_frame.config(width=frame_width)
        self.chat_display_frame.update_idletasks()

    # 考核模式界面
    def start_exam_mode(self):
        global questions
        self.current_mode = "exam"
        questions = self.get_exam_questions()
        if questions:
            self.show_question(0)

    # 生成考题
    def get_exam_questions(self):
        # 修改生成考题的提示，使题目更加精确
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": (
                    "请生成10道关于测试技术与传感器的题目，题目请不要过于简单，比如不要出类似于啥传感器能检测压力（压力传感器）之类的问题，即看题干就能出答案的，每道题目格式如下："
                    "{type='', description='', option='', answer='', explanation=''}。"
                    "其中包含4个选择题，4个填空题和2个简答题。"
                    "请确保题目内容明确、精确，避免多义性。"
                    "对于可能有多种答案的题目，请在题干中明确要求回答其中的一种，或指定特定的方向。"
                    "type为选择、填空、简答三选一，description为题目的描述，"
                    "option为选择题的四个选项格式为A:xxx，B:...，C:...，D:...，"
                    "填空和简答回复None即可，answer为题目的答案，选择题给出正确的选项（A-D），"
                    "填空题给出要填的答案，简答题给出答案，explanation为答案的解释。\n"
                    "请按以下格式一道一道地显示题目：\n"
                    "{type=\"选择\", description=\"1+1=？\", option=\"A:1,B:2,C:3,D:4\", answer=\"B\", explanation=\"略\"}\n"
                    "{type=\"填空\", description=\"古诗补全：床前明月光，_______地上霜。\", option=\"None\", answer=\"疑是\", explanation=\"略\"}\n"
                    "{type=\"简答\", description=\"请说一说为什么压电晶体一压就会产生电？\", option=\"None\", answer=\"因为...\", explanation=\"略\"}"
                )}
            ]
        )
        content = response['choices'][0]['message']['content']
        print("处理后内容:", content)

        # 将伪JSON转换为有效JSON
        try:
            # 去除Markdown代码块和转换近似JSON为有效JSON
            formatted_content = re.sub(r'(\w+)=', r'"\1":', content)  # 将 `key=` 替换为 `"key":`
            json_objects = re.findall(r'\{.*?\}', formatted_content, re.DOTALL)  # 提取每个JSON片段
            questions = [json.loads(obj) for obj in json_objects]  # 解析每个JSON对象
            print("解析后内容:", questions)
            return questions
        except json.JSONDecodeError as e:
            messagebox.showerror("错误", f"解析考题时出错: {e}")
            print("原始内容:", content)
            return []

    # 显示考题
    def show_question(self, index):
        global current_question_index
        self.clear_screen()
        question = questions[index]
        current_question_index = index

        # 题目格式显示
        question_type = question['type']
        question_description = question['description']
        answer_options = question.get('option', '')

        if question_type == "选择":
            self.display_choice_question(question_description, answer_options)
        elif question_type == "填空":
            self.display_fill_question(question_description)
        elif question_type == "简答":
            self.display_open_question(question_description)

        # 显示评判结果（如果有）
        if index in self.evaluation_results:
            evaluation = self.evaluation_results[index]
            evaluation_text = (
                f"\n评判结果: {evaluation['result']}\n"
                f"得分: {evaluation['score']}\n"
                f"评分理由: {evaluation['reason']}\n"
                f"参考答案: {evaluation['correct_answer']}\n"
                f"答案解释: {evaluation['explanation']}"
            )
            evaluation_label = tk.Label(self.root, text=evaluation_text, justify='left', fg='blue')
            evaluation_label.pack(pady=10)

        # 上一题、下一题或提交按钮
        nav_frame = tk.Frame(self.root)
        nav_frame.pack(pady=20)
        if index > 0:
            self.prev_btn = tk.Button(nav_frame, text="上一题", command=lambda: self.show_question(index - 1))
            self.prev_btn.pack(side=tk.LEFT, padx=5)
        if index < len(questions) - 1:
            self.next_btn = tk.Button(nav_frame, text="下一题", command=lambda: self.show_question(index + 1))
            self.next_btn.pack(side=tk.RIGHT, padx=5)
        else:
            self.next_btn = tk.Button(nav_frame, text="提交", command=self.submit_exam)
            self.next_btn.pack(side=tk.RIGHT, padx=5)
        # 返回主菜单按钮
        self.return_btn = tk.Button(nav_frame, text="返回主菜单", command=self.return_to_main)
        self.return_btn.pack(side=tk.RIGHT, padx=5)

    # 显示选择题
    def display_choice_question(self, description, options):
        question_label = tk.Label(self.root, text="选择题: " + description)
        question_label.pack()
        self.var = StringVar()
        # 检查是否已有答案
        if current_question_index in self.user_answers:
            self.var.set(self.user_answers[current_question_index])
        else:
            self.var.set(None)
        for opt in options.split(','):
            opt_label, opt_text = opt.split(':', 1)
            radio_btn = tk.Radiobutton(self.root, text=f"{opt_label}: {opt_text}", variable=self.var, value=opt_label.strip(), command=self.save_choice_answer)
            radio_btn.pack(anchor="w")

    # 保存选择题的答案
    def save_choice_answer(self):
        # 保存选择题的答案，去除前后空格
        self.user_answers[current_question_index] = self.var.get().strip()

    # 显示填空题
    def display_fill_question(self, description):
        question_label = tk.Label(self.root, text="填空题: " + description)
        question_label.pack()
        self.fill_entry = tk.Entry(self.root, width=40)
        # 检查是否已有答案
        if current_question_index in self.user_answers:
            self.fill_entry.insert(0, self.user_answers[current_question_index])
        self.fill_entry.pack(pady=10)
        # 绑定事件，当输入内容变化时保存答案
        self.fill_entry.bind("<KeyRelease>", self.save_fill_answer)

    # 保存填空题的答案
    def save_fill_answer(self, event):
        # 保存填空题的答案
        self.user_answers[current_question_index] = self.fill_entry.get().strip()

    # 显示简答题
    def display_open_question(self, description):
        question_label = tk.Label(self.root, text="简答题: " + description)
        question_label.pack()
        self.answer_text = tk.Text(self.root, height=5, width=50)
        # 检查是否已有答案
        if current_question_index in self.user_answers:
            self.answer_text.insert(tk.END, self.user_answers[current_question_index])
        self.answer_text.pack(pady=10)
        # 绑定事件，当文本内容变化时保存答案
        self.answer_text.bind("<KeyRelease>", self.save_open_answer)

    # 保存简答题的答案
    def save_open_answer(self, event):
        # 保存简答题的答案
        self.user_answers[current_question_index] = self.answer_text.get("1.0", tk.END).strip()

    # 提交考试
    def submit_exam(self):
        total_score = 0
        for index, question in enumerate(questions):
            question_type = question['type']
            description = question['description']
            correct_answer = question['answer'].strip()
            user_answer = self.user_answers.get(index, "").strip()
            evaluation = {}  # 用于保存评判结果
            if question_type == "选择":
                print("用户答案:", user_answer, "正确答案:", correct_answer)
                if user_answer == correct_answer:
                    score = 10
                    evaluation['score'] = 10
                    evaluation['reason'] = '回答正确'
                    result = "正确"
                else:
                    score = 0
                    evaluation['score'] = 0
                    evaluation['reason'] = '回答错误'
                    result = "错误"
                total_score += score
                # 保存评判结果
                self.evaluation_results[index] = {
                    'result': result,
                    'score': score,
                    'reason': evaluation['reason'],
                    'correct_answer': correct_answer,
                    'explanation': question.get('explanation', '')
                }
            elif question_type == "填空":
                if user_answer == correct_answer:
                    score = 10
                    evaluation['score'] = 10
                    evaluation['reason'] = '回答正确'
                    total_score += score
                    # 保存评判结果
                    self.evaluation_results[index] = {
                        'result': '正确',
                        'score': score,
                        'reason': evaluation['reason'],
                        'correct_answer': correct_answer,
                        'explanation': question.get('explanation', '')
                    }
                else:
                    # 使用GPT评判
                    evaluation_text = self.check_answer_with_gpt(question, user_answer)
                    # 解析评判结果
                    evaluation = self.parse_evaluation(evaluation_text)
                    score = evaluation.get('score', 0)
                    total_score += score
                    if score == 0:
                        result= '回答错误'
                    elif score < 10:
                        result = '部分正确'
                    else:
                        result = '正确'
                    # 保存评判结果
                    self.evaluation_results[index] = {
                        'result': result,
                        'score': score,
                        'reason': evaluation.get('reason', ''),
                        'correct_answer': correct_answer,
                        'explanation': question.get('explanation', '')
                    }
            elif question_type == "简答":
                # 使用GPT评判
                evaluation_text = self.check_answer_with_gpt(question, user_answer)
                # 解析评判结果
                evaluation = self.parse_evaluation(evaluation_text)
                score = evaluation.get('score', 0)
                total_score += score
                # 保存评判结果
                self.evaluation_results[index] = {
                    'result': '评分',
                    'score': score,
                    'reason': evaluation.get('reason', ''),
                    'correct_answer': correct_answer,
                    'explanation': question.get('explanation', '')
                }
        # 显示总得分
        messagebox.showinfo("总得分", f"你的总得分是: {total_score}")
        # 显示第一题，供用户查看评判结果
        self.show_question(0)

    # 使用GPT检查答案
    def check_answer_with_gpt(self, question, user_answer):
        prompt = (
            "你将扮演一位严格但公平的阅卷老师，"
            "请根据以下的标准答案和评分标准，评估用户的回答。"
            "满分为10分，请给出得分和简短的评分理由。"
            "如果用户的答案部分正确，也应给予适当的分数。"
            "请注意，答案不需要和标准答案一模一样，只要内容合理、正确即可得分。"
            "但如果用户未作答或答案与题目无关，则得0分。"
            "用户答案后面的内容才是用户的答案，也就是你要测评的内容"
            "请严格按照格式{{score=数字, reason=\"理由\"}}返回，不要有多余的内容。"
        )
        response = openai.ChatCompletion.create(model="gpt-4o", messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"问题：{question['description']}\n参考答案: {question['answer']}\n用户答案：{user_answer}"}
        ])
        return response['choices'][0]['message']['content']

    # 解析GPT的评判结果
    def parse_evaluation(self, evaluation_text):
        # 将evaluation_text解析为字典
        try:
            # 将 '=' 替换为 ':'
            evaluation_text = evaluation_text.replace('=', ':')
            # 使用正则表达式提取score和reason
            pattern = r'\{\s*score\s*:\s*(\d+)\s*,\s*reason\s*:\s*"([^"]*)"\s*\}'
            match = re.search(pattern, evaluation_text)
            if match:
                score = int(match.group(1))
                reason = match.group(2)
                return {'score': score, 'reason': reason}
            else:
                return {'score': 0, 'reason': '无法解析评分结果'}
        except Exception as e:
            print(f"解析评分结果出错: {e}")
            return {'score': 0, 'reason': '无法解析评分结果'}

    # 清除当前界面内容
    def clear_screen(self):
        for widget in self.root.winfo_children():
            widget.destroy()


root = tk.Tk()
app = App(root)
root.mainloop()
