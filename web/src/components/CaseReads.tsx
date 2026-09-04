/**
 * What the screening read from ShipBob: the merchant's claim, the parcel, and the order.
 *
 * Three separate pieces because the screening makes three separate reads, and the screen
 * reports each one as it happened rather than lumping them together.
 *
 * The order lines show a price and a quantity and stop there. Multiplying them out on
 * screen is the obvious next step and is exactly what this project forbids — money is
 * worked out once, by the service. What the order came to is reported with the numbers.
 */
import { formatMoment, formatMoney } from "../display";
import type { Case, Order, Shipment } from "../api/types";

/** The merchant's claim, and their own account of what happened. */
export function ClaimRead({ supportCase }: { supportCase: Case }): React.JSX.Element {
  return (
    <>
      <dl className="record">
        <Row label="Merchant">{supportCase.account_name ?? "—"}</Row>
        <Row label="Merchant account">{supportCase.user_id ?? "—"}</Row>
        <Row label="Kind of claim">{supportCase.sub_category ?? "—"}</Row>
        <Row label="Status">{supportCase.status ?? "—"}</Row>
        <Row label="Opened">{formatMoment(supportCase.created_date)}</Row>
        <Row label="Contact">{supportCase.contact_email ?? "—"}</Row>
      </dl>
      <blockquote className="description">
        {supportCase.description ?? "No description given."}
      </blockquote>
    </>
  );
}

/**
 * How the parcel travelled, and whether it was insured.
 *
 * A missing parcel record is a real answer, not an error: ShipBob had nothing to give us,
 * and two of the four checks have to reckon with that.
 */
export function ParcelRead({ shipment }: { shipment: Shipment | null }): React.JSX.Element {
  if (shipment === null) {
    return <p className="empty">No parcel record.</p>;
  }
  return (
    <dl className="record">
      <Row label="Shipment">{shipment.shipment_id}</Row>
      <Row label="Insured">{shipment.is_insured ? "Yes" : "No"}</Row>
      <Row label="Carrier">{shipment.carrier ?? "—"}</Row>
      <Row label="Tracking">{shipment.tracking_number ?? "—"}</Row>
      <Row label="Status">{shipment.status ?? "—"}</Row>
      <Row label="Delivered">{formatMoment(shipment.delivered_date)}</Row>
    </dl>
  );
}

/** The products the parcel was meant to contain, at the price each was sold for. */
export function OrderRead({ order }: { order: Order | null }): React.JSX.Element {
  if (order === null) {
    return <p className="empty">No order record.</p>;
  }
  return (
    <>
      <dl className="record">
        <Row label="Order">{order.order_id}</Row>
        <Row label="Placed">{formatMoment(order.created_date)}</Row>
      </dl>
      {order.line_items.length === 0 ? (
        <p className="empty">No lines on the order.</p>
      ) : (
        <div className="table-scroll">
          <table className="lines">
            <thead>
              <tr>
                <th scope="col">Product</th>
                <th scope="col">SKU</th>
                <th scope="col" className="numeric">
                  Qty
                </th>
                <th scope="col" className="numeric">
                  Price each
                </th>
              </tr>
            </thead>
            <tbody>
              {order.line_items.map((line, index) => (
                <tr key={line.product_id ?? `${line.name}-${String(index)}`}>
                  <td>{line.name}</td>
                  <td className="mono">{line.sku ?? "—"}</td>
                  <td className="numeric">{line.quantity}</td>
                  <td className="numeric">{formatMoney(line.unit_price)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }): React.JSX.Element {
  return (
    <div className="record-row">
      <dt className="record-key">{label}</dt>
      <dd className="record-value">{children}</dd>
    </div>
  );
}
