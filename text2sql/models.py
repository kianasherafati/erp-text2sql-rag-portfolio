"""Opt-in Hugging Face adapters. Models load only on explicit construction."""


class EmbeddingEncoder:
    def __init__(self, model_id, *, revision=None, local_files_only=False):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_id, revision=revision, device="cpu",
                                         local_files_only=local_files_only, trust_remote_code=False)

    def encode(self, texts):
        return self.model.encode(texts, normalize_embeddings=True, convert_to_numpy=True,
                                 batch_size=1, show_progress_bar=False)


class BGEReranker:
    def __init__(self, *, revision=None, local_files_only=False):
        from sentence_transformers import CrossEncoder
        self.model = CrossEncoder("BAAI/bge-reranker-v2-m3", revision=revision, device="cpu",
                                  max_length=1024, local_files_only=local_files_only,
                                  trust_remote_code=False)

    def score(self, question, documents):
        return self.model.predict([(question, d["text"]) for d in documents],
                                  batch_size=1, show_progress_bar=False).reshape(-1).tolist()


class LocalQwen:
    def __init__(self, *, revision=None, local_files_only=False, quantize=False):
        from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
        model_id = "Qwen/Qwen2.5-Coder-7B-Instruct"
        options = dict(revision=revision, local_files_only=local_files_only, trust_remote_code=False)
        self.tokenizer = AutoTokenizer.from_pretrained(model_id, **options)
        quantization = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                         bnb_4bit_use_double_quant=True) if quantize else None
        self.model = AutoModelForCausalLM.from_pretrained(
            model_id, device_map="auto", dtype="auto", quantization_config=quantization, **options)
        self.model.eval()

    def generate(self, question, documents):
        import torch
        from text2sql.prompt import messages
        record = dict(question=question, tables=[dict(fully_qualified_table=d["full_name"], document=d["text"])
                                                for d in documents])
        prompt = self.tokenizer.apply_chat_template(messages(record), tokenize=False, add_generation_prompt=True)
        encoded = self.tokenizer(prompt, return_tensors="pt", add_special_tokens=False)
        limit = min(28672, self.model.config.max_position_embeddings - 1024)
        if encoded["input_ids"].shape[1] > limit:
            raise ValueError("SCHEMA_CONTEXT_EXCEEDS_BUDGET")
        encoded = {k: v.to(self.model.device) for k, v in encoded.items()}
        with torch.inference_mode():
            output = self.model.generate(**encoded, do_sample=False, max_new_tokens=1024,
                                         pad_token_id=self.tokenizer.eos_token_id)
        tokens = output[0, encoded["input_ids"].shape[1]:]
        if tokens.shape[0] >= 1024:
            raise ValueError("INCOMPLETE_OUTPUT")
        return self.tokenizer.decode(tokens, skip_special_tokens=True)
