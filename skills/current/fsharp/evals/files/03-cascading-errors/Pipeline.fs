namespace Cascades

type Customer = { Name: string; Code: int }
type Shipment = { Name: string; Code: string }

module Pipeline =
    let normalize text = text.Trim().ToUpperInvariant()

    let customerCode entry = entry.Code + 100

    let labels (customers: Customer list) =
        customers
        |> List.map (fun customer -> normalize customer.Name, customerCode customer)

    let shipmentLabels (shipments: Shipment list) =
        shipments |> List.map (fun shipment -> normalize shipment.Name, shipment.Code)

    let summarize customers shipments =
        labels customers, shipmentLabels shipments
