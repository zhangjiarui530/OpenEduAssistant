from bigdl.llm.transformers import AutoModel
from transformers import AutoTokenizer
from bigdl.llm.transformers import AutoModelForCausalLM
import torch
import time
import os

from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer

start_time = time.time()  # 记录开始时间


# device = torch.device("xpu")

class PDFFileLoader():
    def __init__(self, file) -> None:
        nums = list(range(107, 108))
        # self.paragraphs = self.extract_text_from_pdf(file, page_numbers=[106, 107, 108, 109, 110])
        # self.paragraphs = self.extract_text_from_pdf(file, page_numbers=[60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73])
        # self.paragraphs = self.extract_text_from_pdf(file)
        self.paragraphs = self.extract_text_from_pdf(file, page_numbers=nums)
        i = 1
        for para in self.paragraphs[:5]:
            print(f"========= 第{i}段 ==========")
            print(para + "\n")
            i += 1

    def getParagraphs(self):
        return self.paragraphs

    ################################# 文档的加载与切割 ############################
    def extract_text_from_pdf(self, filename, page_numbers=None):
        '''从 PDF 文件中（按指定页码）提取文字'''
        paragraphs = []
        buffer = ''
        full_text = ''
        # 提取全部文本
        for i, page_layout in enumerate(extract_pages(filename)):
            # 如果指定了页码范围，跳过范围外的页
            if page_numbers is not None and i not in page_numbers:
                continue
            for element in page_layout:
                if isinstance(element, LTTextContainer):
                    full_text += element.get_text() + '\n'

        # 段落分割
        lines = full_text.split('。\n')
        for text in lines:
            buffer = text.strip(' ').replace('\n', ' ').replace('[', '').replace(']', '')  ## 1. 去掉特殊字符
            if len(buffer) < 10:  ## 2. 过滤掉长度小于 10 的段落，这可能会导致一些信息丢失，慎重使用，实际生产中不能用
                continue
            if buffer:
                paragraphs.append(buffer)
                buffer = ''
                row_count = 0

        if buffer and len(buffer) > 10:  ## 3. 过滤掉长度小于 10 的段落，这可能会导致一些信息丢失，慎重使用，实际生产中不能用
            paragraphs.append(buffer)
        return paragraphs


model_path = r'C:\model\THUDM\chatglm3-6b'
# model_path = r'C:\model\Qwen\Qwen1.5-4B-Chat'
save_directory = r"C:\开放原子\4.17\model_low_bit"
model = AutoModelForCausalLM.load_low_bit(save_directory, trust_remote_code=True)
model = model.to('xpu')
tokenizer = AutoTokenizer.from_pretrained(model_path,
                                          trust_remote_code=True)


# from peft import get_peft_config, get_peft_model, LoraConfig, TaskType
# peft_config = LoraConfig(
#     task_type="CAUSAL_LM", inference_mode=False, r=8, lora_alpha=32, lora_dropout=0.1
# )
# model = get_peft_model(model, peft_config)

def generate_text_from_model(prompt, max_tokens=4096):
    # Prepare the prompt
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": prompt}
    ]
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    model_inputs = tokenizer([text], return_tensors="pt").to('xpu')
    # Generate text
    with torch.inference_mode():
        generated_ids = model.generate(model_inputs.input_ids, max_new_tokens=1024)
        generated_ids = [output_ids[len(input_ids):] for input_ids, output_ids in
                         zip(model_inputs.input_ids, generated_ids)]
        torch.xpu.synchronize()
        # generated_ids = generated_ids.cpu()
        response = tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
    return response


def get_embeddings(texts):
    '''使用本地 Qwen1.5-4B-Chat 模型获取文本的嵌入向量'''
    # inputs = tokenizer(texts, padding=True, truncation=True, return_tensors="pt")
    inputs = tokenizer(texts, padding=True, truncation=True, return_tensors="pt").to('xpu')
    with torch.no_grad():
        outputs = model(**inputs)
    # 使用模型头部的隐藏状态作为嵌入向量
    return outputs.logits.mean(dim=1).tolist()
# return outputs.last_hidden_state


# from openai import OpenAI
# from dotenv import load_dotenv, find_dotenv
# _ = load_dotenv(find_dotenv())  # 读取本地 .env 文件，里面定义了 OPENAI_API_KEY
# client = OpenAI()
# def get_embeddings(texts, model="text-embedding-3-small"):
#     '''封装 OpenAI 的 Embedding 模型接口'''
#     data = client.embeddings.create(input=texts, model=model).data
#     return [x.embedding for x in data]


import chromadb
from chromadb.config import Settings

class MyVectorDBConnector:
    def __init__(self, collection_name, embedding_fn):
        # chroma_client = chromadb.Client(Settings(allow_reset=True))
        # chroma_client = chromadb.PersistentClient(path=r"C:\bigdl\test\chromadb")
        '''先在终端运行 chroma run --path C:\开放原子\4.18\class_assistant\data\db '''
        chroma_client = chromadb.HttpClient(host='localhost', port=8000)

        # 为了演示，实际不需要每次 reset()
        # chroma_client.reset()

        # 创建一个 collection
        self.collection = chroma_client.get_or_create_collection(name=collection_name)
        self.embedding_fn = embedding_fn

    def add_documents(self, documents):
        '''向 collection 中添加文档与向量'''
        self.collection.add(
            embeddings=self.embedding_fn(documents),  # 每个文档的向量
            documents=documents,  # 文档的原文
            ids=[f"id{i}" for i in range(len(documents))]  # 每个文档的 id
        )

    def search(self, query, top_n):
        '''检索向量数据库'''
        results = self.collection.query(
            query_embeddings=self.embedding_fn([query]),
            n_results=top_n
        )
        return results

    def q_search(self, query, top_n):
        results = self.collection.query(
            query_embeddings=self.embedding_fn([query]),
            n_results=top_n
        )
        return results


def build_prompt(prompt_template, **kwargs):
    '''将 Prompt 模板赋值'''
    prompt = prompt_template
    for k, v in kwargs.items():
        if isinstance(v, str):
            val = v
        elif isinstance(v, list) and all(isinstance(elem, str) for elem in v):
            val = '\n'.join(v)
        else:
            val = str(v)
        prompt = prompt.replace(f"__{k.upper()}__", val)
    return prompt


prompt_template = """
你是一个智能助教。
你的任务是根据下述给定的已知信息回答用户问题。
确保你的回复完全依据下述已知信息，不要编造答案，回答的内容务必符合中文语法规范，通顺流畅，简短精炼。
如果下述已知信息不足以回答用户的问题，请直接回复"与教材无关，我无法回答您的问题"。

已知信息:
__INFO__

用户问：
__QUERY__

请用中文回答用户问题。
"""

prompt_question = """
你是一个优秀的中文出题助手,你的任务是根据下述给定的已知信息为用户出给定题目数量的题.
比如题目类型是选择题，题目数量是3，那么你就帮用户出3道选择题，并且每道题的都要给出正确答案，以此类推。
确保出的题目必须与用户要求、题目类型、题目数量的相符。不要胡编乱造，不要有无关的符号。
如果题目类型是填空题，那么你要出需要填空的题，并给出正确答案，不要说多余的话。
如果题目类型是问答题，那么你需要用中文出题，并且用中文给出正确的回答，尽量简短精炼。
如果下述已知信息不足以出题，请直接回复"与教材无关，我无法完成您的任务"。
如果能回答，那么prompt里的话请不要输出

已知信息:
__INFO__

用户要求：
__QUERY__

题目类型：
__TYPE__

题目数量：
__NUM__

请用中文表达。
"""

prompt_code = """
你是一个优秀的代码智能助手。
你的任务是扮演下述给定的角色回答用户与代码有关的问题。
如果下述已知信息不足以回答用户的问题，请直接回复"我无法回答您的问题"。

角色:
__ROLE__

用户问：
__QUERY__

请用中文回答用户问题，并且不要输出prompt里的内容。
"""


def get_completion(prompt):
    # Prepare the prompt
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": prompt}
    ]
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    model_inputs = tokenizer([text], return_tensors="pt").to('xpu')

    # Generate text
    with torch.inference_mode():
        generated_ids = model.generate(model_inputs.input_ids, max_new_tokens=1024)
        generated_ids = [output_ids[len(input_ids):] for input_ids, output_ids in
                         zip(model_inputs.input_ids, generated_ids)]
        torch.xpu.synchronize()
        # generated_ids = generated_ids.cpu()
        response = tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]

    return response

# def get_completion(prompt, model="gpt-3.5-turbo-16k-0613"):
#     '''封装 openai 接口'''
#     messages = [{"role": "user", "content": prompt}]
#     response = client.chat.completions.create(
#         model=model,
#         messages=messages,
#         temperature=0.2,  # 模型输出的随机性，0 表示随机性最小
#     )
#     return response.choices[0].message.content
#
#
# def generate_text_from_model(prompt, model="gpt-3.5-turbo-16k-0613"):
#     '''封装 openai 接口'''
#     messages = [{"role": "user", "content": prompt}]
#     response = client.chat.completions.create(
#         model=model,
#         messages=messages,
#         temperature=0.2,  # 模型输出的随机性，0 表示随机性最小
#     )
#     return response.choices[0].message.content


class Chat_Bot:
    def __init__(self, n_results=2):
        self.llm_api = get_completion
        self.n_results = n_results

    def createVectorDB(self, file):
        print(file)
        # pdf_loader = PDFFileLoader(file)
        # 创建一个向量数据库对象
        self.vector_db = MyVectorDBConnector("demo", get_embeddings)
        # 向向量数据库中添加文档，灌入数据
        # self.vector_db.add_documents(pdf_loader.getParagraphs())

    def chat(self, user_query):
        # 1. 检索
        search_results = self.vector_db.search(user_query, self.n_results)

        # 2. 构建 Prompt
        prompt = build_prompt(prompt_template, info=search_results['documents'][0], query=user_query)
        print("prompt===================>")
        print(prompt)

        # 3. 调用 LLM
        response = self.llm_api(prompt)
        return response

    def question(self, user_query, type, num):
        search_results = self.vector_db.q_search(user_query, 5)
        prompt = build_prompt(prompt_question, info=search_results['documents'][0], query=user_query, type=type,
                              num=num)
        print("prompt===================>")
        print(prompt)
        response = self.llm_api(prompt)
        return response

    def code(self, role, user_query):
        prompt = build_prompt(prompt_code, role=role, query=user_query)
        print("prompt===================>")
        print(prompt)

        response = self.llm_api(prompt)
        return response


# start_time = time.time()  # 记录开始时间
# chat_bot = Chat_Bot()
# # chat_bot.createVectorDB(r"C:\bigdl\chat_bot\docs\信息系统正文_三样.pdf")
# chat_bot.createVectorDB(r"C:\OpenEdu\class_assistant\docs\信息系统概论_教材.pdf")
#
# response = chat_bot.chat("计算机病毒的特征是什么？")
# # response = chat_bot.chat("lora是什么？")
# print()
# print("response=====================>")
# print(response)

# response1 = chat_bot.chat("计算机病毒的特征是什么？")
# print()
# print("response1=====================>")
# print(response1)

end_time = time.time()  # 记录结束时间
elapsed_time = end_time - start_time  # 计算总时间
print(f"执行时间为: {elapsed_time:.4f} 秒")
