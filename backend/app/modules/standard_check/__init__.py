"""标准校验模块（P0）。

职责：选择合同条款 → 标准匹配结果。

实现链路：
    loader.py    加载 data/standards/*.json，摊平成"一条条款一个条目"
    store.py     哈希向量 + BM25 混合排序的轻量检索层
    service.py   逐条校验合同条款，给出匹配分数、覆盖率与未覆盖项
    router.py    HTTP 接口

接口：
    GET  /api/v1/standards           标准库目录
    GET  /api/v1/standards/stats     检索库状态
    POST /api/v1/standards/search    按文本检索标准条款
    POST /api/v1/standards/check     校验某份合同的全部条款
    POST /api/v1/standards/reindex   重建检索库

跨机说明：
    Windows 开发机用 EMBEDDING_PROVIDER=hashing + VECTOR_STORE_BACKEND=simple，
    零依赖即可运行；Linux 主力机换成 local + chroma 后，本模块代码无需改动。
"""
