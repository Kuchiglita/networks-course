import os
from typing import Optional, List
from fastapi import FastAPI, HTTPException, status, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="Shop Service")

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# CREATE (id is automatically provided by server)
class ProductCreate(BaseModel):
    name: str
    description: str


# PUT
class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


# Full item scheme with optional icon (task В)
class Product(BaseModel):
    id: int
    name: str
    description: str
    icon: Optional[str] = None


products_db: dict[int, Product] = {}  # product_id - Product
next_id: int = 1


@app.post("/product", response_model=Product, status_code=status.HTTP_201_CREATED)
def create_product(product_in: ProductCreate):
    global next_id
    new_product = Product(
        id=next_id,
        name=product_in.name,
        description=product_in.description,
        icon=None
    )
    products_db[next_id] = new_product
    next_id += 1
    return new_product


@app.get("/products", response_model=List[Product])
def get_all_products():
    return list(products_db.values())


@app.get("/product/{product_id}", response_model=Product)
def get_product(product_id: int):
    if product_id not in products_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with id {product_id} not found"
        )
    return products_db[product_id]


@app.put("/product/{product_id}", response_model=Product)
def update_product(product_id: int, product_update: ProductUpdate):
    if product_id not in products_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with id {product_id} not found"
        )

    current_product = products_db[product_id]

    updated_name = product_update.name if product_update.name is not None else current_product.name
    updated_description = product_update.description if product_update.description is not None else current_product.description

    updated_product = Product(
        id=current_product.id,
        name=updated_name,
        description=updated_description,
        icon=current_product.icon
    )
    products_db[product_id] = updated_product
    return updated_product


@app.delete("/product/{product_id}", response_model=Product)
def delete_product(product_id: int):
    if product_id not in products_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with id {product_id} not found"
        )
    deleted_product = products_db.pop(product_id)
    return deleted_product


@app.post("/product/{product_id}/image", response_model=Product)
async def upload_product_image(product_id: int, file: UploadFile = File(...)):
    if product_id not in products_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with id {product_id} not found"
        )

    ext = os.path.splitext(file.filename)[1] if file.filename else ".png"
    file_path = os.path.join(UPLOAD_DIR, f"product_{product_id}{ext}")

    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    products_db[product_id].icon = file_path
    return products_db[product_id]


@app.get("/product/{product_id}/image")
def get_product_image(product_id: int):
    if product_id not in products_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with id {product_id} not found"
        )

    product = products_db[product_id]
    if not product.icon or not os.path.exists(product.icon):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found for this product"
        )

    return FileResponse(product.icon)