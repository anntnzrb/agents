namespace Inventory

type ProductCode = private ProductCode of string

module ProductCode =
    val tryCreate: string | null -> Result<ProductCode, string>
    val value: ProductCode -> string
