from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from typing import List, Optional
import time
import asyncpg
import os

# Função para obter a conexão com o banco de dados PostgreSQL
async def get_database():
    DATABASE_URL = os.environ.get("PGURL", "postgres://postgres:postgres@db:5432/albuns") 
    return await asyncpg.connect(DATABASE_URL)

# Inicializar a aplicação FastAPI
app = FastAPI()

# Modelo para adicionar novos albuns
class Album(BaseModel):
    id: Optional[int] = None
    titulo: str
    cantor: str
    quantidade: int
    preco: float

class AlbumBase(BaseModel):
    titulo: str
    cantor: str
    quantidade: int
    preco: float

# Modelo para venda de albuns
class VendaAlbum(BaseModel):
    quantidade: int

# Modelo para atualizar atributos de um album (exceto o ID)
class AtualizarAlbum(BaseModel):
    titulo: Optional[str] = None
    cantor: Optional[str] = None
    quantidade: Optional[int] = None
    preco: Optional[float] = None

# Middleware para logging
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    print(f"Path: {request.url.path}, Method: {request.method}, Process Time: {process_time:.4f}s")
    return response

# Função para verificar se o album existe usando cantor e nome do album
async def album_existe(titulo: str, cantor: str, conn: asyncpg.Connection):
    try:
        query = "SELECT * FROM albuns WHERE LOWER(titulo) = LOWER($1) AND LOWER(cantor) = LOWER($2)"
        result = await conn.fetchval(query, titulo, cantor)
        return result is not None
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Falha ao verificar se o album existe: {str(e)}")

# 1. Adicionar um novo album
@app.post("/api/v1/albuns/", status_code=201)
async def adicionar_album(album: AlbumBase):
    conn = await get_database()
    if await album_existe(album.titulo, album.cantor, conn):
        raise HTTPException(status_code=400, detail="Album já existe.")
    try:
        query = "INSERT INTO albuns (titulo, cantor, quantidade, preco) VALUES ($1, $2, $3, $4)"
        async with conn.transaction():
            result = await conn.execute(query, album.titulo, album.cantor, album.quantidade, album.preco)
            return {"message": "Album adicionado com sucesso!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Falha ao adicionar o album: {str(e)}")
    finally:
        await conn.close()

# 2. Listar todos os albuns
@app.get("/api/v1/albuns/", response_model=List[Album])
async def listar_albuns():
    conn = await get_database()
    try:
        # Buscar todos os albuns no banco de dados
        query = "SELECT * FROM albuns"
        rows = await conn.fetch(query)
        albuns = [dict(row) for row in rows]
        return albuns
    finally:
        await conn.close()

# 3. Buscar album por ID
@app.get("/api/v1/albuns/{album_id}")
async def listar_album_por_id(album_id: int):
    conn = await get_database()
    try:
        # Buscar o album por ID
        query = "SELECT * FROM albuns WHERE id = $1"
        album = await conn.fetchrow(query, album_id)
        if album is None:
            raise HTTPException(status_code=404, detail="Album não encontrado.")
        return dict(album)
    finally:
        await conn.close()

# 4. Vender um album (reduzir quantidade no estoque)
@app.put("/api/v1/albuns/{album_id}/vender/")
async def vender_album(album_id: int, venda: VendaAlbum):
    conn = await get_database()
    try:
        # Verificar se o album existe
        query = "SELECT * FROM albuns WHERE id = $1"
        album = await conn.fetchrow(query, album_id)
        if album is None:
            raise HTTPException(status_code=404, detail="Album não encontrado.")

        # Verificar se a quantidade no estoque é suficiente
        if album['quantidade'] < venda.quantidade:
            raise HTTPException(status_code=400, detail="Quantidade insuficiente no estoque.")

        # Atualizar a quantidade no banco de dados
        nova_quantidade = album['quantidade'] - venda.quantidade
        update_query = "UPDATE albuns SET quantidade = $1 WHERE id = $2"
        await conn.execute(update_query, nova_quantidade, album_id)


        # Calcular o valor total da venda
        valor_venda = album['preco'] * venda.quantidade
        # Registrar a venda na tabela de vendas
        insert_venda_query = """
            INSERT INTO vendas (album_id, quantidade_vendida, valor_venda) 
            VALUES ($1, $2, $3)
        """
        await conn.execute(insert_venda_query, album_id, venda.quantidade, valor_venda)

        # Criar um novo dicionário com os dados atualizados
        album_atualizado = dict(album)
        album_atualizado['quantidade'] = nova_quantidade

        return {"message": "Venda realizada com sucesso!", "album": album_atualizado}
    finally:
        await conn.close()

# 5. Atualizar atributos de um album pelo ID (exceto o ID)
@app.patch("/api/v1/albuns/{album_id}")
async def atualizar_album(album_id: int, album_atualizacao: AtualizarAlbum):
    conn = await get_database()
    try:
        # Verificar se o album existe
        query = "SELECT * FROM albuns WHERE id = $1"
        livro = await conn.fetchrow(query, album_id)
        if livro is None:
            raise HTTPException(status_code=404, detail="Album não encontrado.")

        # Atualizar apenas os campos fornecidos
        update_query = """
            UPDATE albuns
            SET titulo = COALESCE($1, titulo),
                cantor = COALESCE($2, cantor),
                quantidade = COALESCE($3, quantidade),
                preco = COALESCE($4, preco)
            WHERE id = $5
        """
        await conn.execute(
            update_query,
            album_atualizacao.titulo,
            album_atualizacao.cantor,
            album_atualizacao.quantidade,
            album_atualizacao.preco,
            album_id
        )
        return {"message": "Album atualizado com sucesso!"}
    finally:
        await conn.close()

# 6. Remover um album pelo ID
@app.delete("/api/v1/albuns/{album_id}")
async def remover_album(album_id: int):
    conn = await get_database()
    try:
        # Verificar se o album existe
        query = "SELECT * FROM albuns WHERE id = $1"
        album = await conn.fetchrow(query, album_id)
        if album is None:
            raise HTTPException(status_code=404, detail="Album não encontrado.")

        # Remover o album do banco de dados
        delete_query = "DELETE FROM albuns WHERE id = $1"
        await conn.execute(delete_query, album_id)
        return {"message": "Album removido com sucesso!"}
    finally:
        await conn.close()

# 7. Resetar repositorio de albuns
@app.delete("/api/v1/albuns/")
async def resetar_albuns():
    init_sql = os.getenv("INIT_SQL", "db/init.sql")
    conn = await get_database()
    try:
        # Read SQL file contents
        with open(init_sql, 'r') as file:
            sql_commands = file.read()
        # Execute SQL commands
        await conn.execute(sql_commands)
        return {"message": "Banco de dados limpo com sucesso!"}
    finally:
        await conn.close()


# 8 . Listar vendas
@app.get("/api/v1/vendas/")
async def listar_vendas():
    conn = await get_database()
    try:
        # Buscar todas as vendas no banco de dados
        query = "SELECT * FROM vendas"
        rows = await conn.fetch(query)
        vendas = [dict(row) for row in rows]
        return vendas
    finally:
        await conn.close()