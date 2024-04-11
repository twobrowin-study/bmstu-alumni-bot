from enum import Enum
from fastapi import Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse

from typing import Annotated
from fastapi.exceptions import HTTPException
from starlette.status import HTTP_401_UNAUTHORIZED

from loguru import logger

from ui.setup import provider, templates

from utils.db_model import Base

from sqlalchemy import insert, update
from sqlalchemy.exc import IntegrityError

async def verify_token(token: Annotated[str, Depends(provider.oauth2_scheme)]) -> str:
    """
    Убедиться в корректности токена
    """
    logger.info(f"Received Bearer token with request")
    try:
        user = provider.keycloak.decode_token(token)
        if 'preferred_username' in user:
            logger.success(f"Request from user {user['preferred_username']}")
        else:
            logger.warning(f"Request from user without preferred_username!!!")
    except Exception as e:
        logger.info(f"Bearer token could not be verified: {e}")
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail=f"Bearer token could not be verified: {e}")
    return token

def template(request: Request, template_name: str, additional_context: dict) -> HTMLResponse:
    """
    Прослойка для стандартизации вывода шиблонов
    """
    return templates.TemplateResponse(
        request=request, name=template_name,
        context = {
            'uri_prefix': provider.config.path_prefix,
            'i18n':       provider.config.i18n,
            'keycloak':   provider.config.keycloak
        } | additional_context
    )

async def get_request_data_or_responce(request: Request, type_str: str) -> tuple[dict[str, dict[str, str|dict[str, str]]], JSONResponse|None]:
    request_data = await request.json()

    bad_responce = JSONResponse({'error': True}, status_code=500)

    if not isinstance(request_data, dict):
        logger.error("Found unknown request type...")
        return {}, bad_responce

    if type_str not in request_data:
        logger.error(f"Type {type_str} not in request...")
        return {}, bad_responce
    
    typed_request_data = request_data[type_str]
    if not isinstance(typed_request_data, dict):
        logger.error(f"Type {type_str} is bad type request...")
        return {}, bad_responce

    return typed_request_data, None

def prepare_attrs_object_from_request(
        request_data: dict[str, dict[str, str|dict[str, str]]],
        status_type: type[Enum],
        numeric_keys: list[str] = []
    ) -> tuple[dict[str|int, dict[str, str|Enum|bool|int]], JSONResponse|None]:
    bad_responce = JSONResponse({'error': True}, status_code=500)
    attrs: dict[str|int, dict[str, str|Enum|bool|int]] = {}
    for idx, plain_obj in request_data.items():
        if idx != 'new' and not idx.isnumeric():
            logger.warning(f"Got bad id {idx=}")
            return {}, bad_responce

        if idx.isnumeric():
            idx = int(idx)
        
        obj: dict[str, str|Enum] = {}
        for key, value in plain_obj.items():
            if key in numeric_keys:
                try:
                    obj[key] = int(value)
                except Exception:
                    logger.warning(f"Got value error as {key=} should be numeric but gor {value=}")
                    return {}, bad_responce
            elif isinstance(value, str):
                if value == "":
                    obj[key] = None
                else:
                    obj[key] = value
            elif isinstance(value, dict):
                if 'bool_value' in value:
                    obj[key] = True if value['bool_value'] == 'true' else False
                elif 'id_value' in value:
                    obj[key] = None if value['id_value'] == 'None' else int(value['id_value'])
                else:
                    obj[key] = status_type(**value)
            else:
                logger.warning(f"Got bad key value pair {key=} {value=}")
                return {}, bad_responce

        attrs[idx] = obj
    return attrs, None

async def try_to_save_attrs(db_type: type[Base], db_attrs: dict[str|int, dict[str, str|Enum|bool|int]]) -> JSONResponse:
    async with provider.db_session() as session:
        for idx,db_attr in db_attrs.items():
            if idx == 'new':
                await session.execute(
                    insert(db_type).values(**db_attr)
                )
            else:
                await session.execute(
                    update(db_type)
                    .where(db_type.id == idx)
                    .values(**db_attr)
                )
        try:
            await session.commit()
            logger.success(f"Updated {db_type.__name__} table...")
            return JSONResponse({'error': False})
        except IntegrityError as err:
            logger.error(err)
            await session.rollback()
            logger.error(f"Did not updated {db_type.__name__} table...")
            return JSONResponse({'error': True}, status_code=500)