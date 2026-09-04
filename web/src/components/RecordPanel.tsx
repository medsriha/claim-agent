/**
 * What the screening actually read: the merchant's case, the parcel, and the order.
 *
 * This is here so a rep can see the claim itself rather than only the verdict on it —
 * the merchant's own description of what happened is often the first thing they want.
 *
 * **The order lines show a price and a quantity and stop there.** Multiplying them out to
 * show what each line was worth is the obvious next step and is exactly what this project
 * forbids on screen: money is worked out once, by the service, exactly. What the order
 * came to is in the panel above this one, and it got there that way.
 */
import { formatMoment, formatMoney } from "../display";
import type { CaseRecord } from "../api/types";

interface RecordPanelProps {
  record: CaseRecord;
}

export function RecordPanel({ record }: RecordPanelProps): React.JSX.Element {
  const { case: supportCase, shipment, order } = record;

  return (
    <section className="panel">
      <h3 className="panel-title">What we read</h3>

      <h4 className="subhead">The claim</h4>
      <dl className="record">
        <Row label="Merchant">{supportCase.account_name ?? "not recorded"}</Row>
        <Row label="Merchant account">{supportCase.user_id ?? "not recorded"}</Row>
        <Row label="Kind of claim">{supportCase.sub_category ?? "not recorded"}</Row>
        <Row label="Status">{supportCase.status ?? "not recorded"}</Row>
        <Row label="Opened">{formatMoment(supportCase.created_date)}</Row>
        <Row label="Contact">{supportCase.contact_email ?? "not recorded"}</Row>
      </dl>
      <blockquote className="description">
        {supportCase.description ?? "The merchant described nothing."}
      </blockquote>

      <h4 className="subhead">The parcel</h4>
      {shipment === null ? (
        <p className="empty">
          No parcel record. Either the claim named none, or it could not be read.
        </p>
      ) : (
        <dl className="record">
          <Row label="Shipment">{shipment.shipment_id}</Row>
          <Row label="Insured">{shipment.is_insured ? "Yes" : "No"}</Row>
          <Row label="Carrier">{shipment.carrier ?? "not recorded"}</Row>
          <Row label="Tracking">{shipment.tracking_number ?? "not recorded"}</Row>
          <Row label="Status">{shipment.status ?? "not recorded"}</Row>
          <Row label="Delivered">{formatMoment(shipment.delivered_date)}</Row>
        </dl>
      )}

      <h4 className="subhead">The order</h4>
      {order === null ? (
        <p className="empty">
          No order record. Either the claim named none, or it could not be read — which is
          not the same as an order with nothing on it.
        </p>
      ) : (
        <>
          <dl className="record">
            <Row label="Order">{order.order_id}</Row>
            <Row label="Placed">{formatMoment(order.created_date)}</Row>
          </dl>
          {order.line_items.length === 0 ? (
            <p className="empty">The order has no lines on it.</p>
          ) : (
            <div className="table-scroll">
              <table className="lines">
                <thead>
                  <tr>
                    <th scope="col">Product</th>
                    <th scope="col">SKU</th>
                    <th scope="col" className="numeric">
                      Quantity
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
      )}
    </section>
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
