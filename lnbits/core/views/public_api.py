import trio
import datetime
from http import HTTPStatus

from lnbits import bolt11

from .. import core_app
from ..crud import get_standalone_payment
from ..tasks import api_invoice_listeners


@core_app.get("/public/v1/payment/{payment_hash}")
async def api_public_payment_longpolling(payment_hash):
    payment = await get_standalone_payment(payment_hash)

    if not payment:
        return {"message": "Payment does not exist."}, HTTPStatus.NOT_FOUND
    elif not payment.pending:
        return {"status": "paid"}, HTTPStatus.OK

    try:
        invoice = bolt11.decode(payment.bolt11)
        expiration = datetime.datetime.fromtimestamp(invoice.date + invoice.expiry)
        if expiration < datetime.datetime.now():
            return {"status": "expired"}, HTTPStatus.OK
    except:
        return {"message": "Invalid bolt11 invoice."}, HTTPStatus.BAD_REQUEST

    send_payment, receive_payment = trio.open_memory_channel(0)

    print("adding standalone invoice listener", payment_hash, send_payment)
    api_invoice_listeners.append(send_payment)

    response = None

    async def payment_info_receiver(cancel_scope):
        async for payment in receive_payment:
            if payment.payment_hash == payment_hash:
                nonlocal response
                response = ({"status": "paid"}, HTTPStatus.OK)
                cancel_scope.cancel()

    async def timeouter(cancel_scope):
        await trio.sleep(45)
        cancel_scope.cancel()

    async with trio.open_nursery() as nursery:
        nursery.start_soon(payment_info_receiver, nursery.cancel_scope)
        nursery.start_soon(timeouter, nursery.cancel_scope)

    if response:
        return response
    else:
        return {"message": "timeout"}, HTTPStatus.REQUEST_TIMEOUT
