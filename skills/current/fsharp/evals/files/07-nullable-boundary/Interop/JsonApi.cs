using System.Text.Json;
namespace Interop;
public sealed class PersonDto
{
    public string? Name { get; set; }
    public int? Age { get; set; }
}
public static class JsonApi
{
    public static PersonDto? Deserialize(string json) => JsonSerializer.Deserialize<PersonDto>(json);
}
